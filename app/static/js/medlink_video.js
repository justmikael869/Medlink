/*
  MedLink video consultation (browser side).

  Ported from the Liwec project's webrtc.js and trimmed to a two-person call
  (patient + doctor). Socket.IO carries only the set-up messages; the audio
  and video go directly between the two browsers.

  Notable fixes over the Liwec version:
   - network candidates that arrive early are queued instead of dropped
   - a brief network wobble no longer ends the call immediately
   - a person with no camera/mic can still see and hear the other side
   - reconnecting the socket re-joins the room cleanly
   - all names/chat text are inserted as plain text (no HTML injection)
*/
(function () {
  'use strict';
  const cfg = window.VIDEO_CONFIG;
  const $ = (id) => document.getElementById(id);

  const els = {
    remoteVideo: $('remote-video'), placeholder: $('remote-placeholder'),
    initial: $('remote-initial'), wait: $('remote-wait'),
    status: $('vr-status'), label: $('remote-label'), name: $('remote-name'),
    muted: $('remote-muted'), localVideo: $('local-video'),
    localBox: $('local-box'), localOff: $('local-off'),
    btnMic: $('btn-mic'), btnCam: $('btn-cam'), btnShare: $('btn-share'),
    btnChat: $('btn-chat'), btnHangup: $('btn-hangup'),
    wrap: $('vr-wrap'), msgs: $('vr-msgs'), form: $('vr-chat-form'),
    input: $('vr-chat-input'), unread: $('chat-unread'),
  };

  const socket = io();
  const peers = {};        // sid -> { pc, pending: [], timer }
  const knownMeta = {};    // sid -> { name }
  let localStream = null;
  let cameraTrack = null;
  let screenStream = null;
  let ready = false;
  let ended = false;
  let remoteStream = null;
  let unreadCount = 0;

  /* ---------------- small UI helpers ---------------- */

  function setStatus(text, autoHideMs) {
    els.status.textContent = text || '';
    els.status.style.display = text ? 'block' : 'none';
    if (text && autoHideMs) {
      const t = text;
      setTimeout(() => { if (els.status.textContent === t) setStatus(''); }, autoHideMs);
    }
  }

  function showRemotePlaceholder(message) {
    els.placeholder.style.display = 'flex';
    els.remoteVideo.style.display = 'none';
    els.wait.textContent = message;
  }

  function showRemoteVideo() {
    els.placeholder.style.display = 'none';
    els.remoteVideo.style.display = 'block';
  }

  function setRemoteName(name) {
    els.initial.textContent = (name || '?').replace(/^Dr\.\s*/, '').charAt(0).toUpperCase() || '?';
    els.name.textContent = name || '';
    els.label.style.display = name ? 'flex' : 'none';
  }

  function setBtn(btn, iconClass, label, cls) {
    btn.querySelector('i').className = 'ti ' + iconClass;
    btn.querySelector('span').textContent = label;
    btn.classList.remove('off', 'on');
    if (cls) btn.classList.add(cls);
  }

  function myMediaState() {
    const a = localStream && localStream.getAudioTracks()[0];
    const v = cameraTrack;
    return { audio: !!(a && a.enabled), video: !!(v && v.enabled) };
  }

  function broadcastMediaState() {
    if (socket.connected && ready) socket.emit('media_state', myMediaState());
  }

  /* ---------------- local camera / microphone ---------------- */

  async function getLocalMedia() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setStatus('Camera and microphone need a secure (https) connection.');
      return new MediaStream();
    }
    try {
      return await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
    } catch (e1) {
      console.warn('Camera+mic unavailable, trying microphone only:', e1);
    }
    try {
      setStatus('Camera unavailable: joining with audio only.', 6000);
      return await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e2) {
      console.warn('No microphone either:', e2);
      setStatus('No camera or microphone available. You can still see and hear the other person.', 8000);
      return new MediaStream();
    }
  }

  async function init() {
    setRemoteName(cfg.otherName);
    els.label.style.display = 'none';
    showRemotePlaceholder('Waiting for ' + cfg.otherName + ' to join…');

    localStream = await getLocalMedia();
    cameraTrack = localStream.getVideoTracks()[0] || null;
    els.localVideo.srcObject = localStream;

    if (!cameraTrack) {
      els.localOff.style.display = 'flex';
      els.btnCam.style.display = 'none';
    }
    if (!localStream.getAudioTracks()[0]) els.btnMic.style.display = 'none';
    if (cameraTrack && navigator.mediaDevices.getDisplayMedia) els.btnShare.style.display = '';

    ready = true;
    if (socket.connected) joinRoom();
    else setStatus('Connecting…');
  }

  function joinRoom() {
    setStatus('Joining…');
    socket.emit('join', { appt_id: cfg.apptId });
  }

  /* ---------------- socket events ---------------- */

  socket.on('connect', () => {
    if (!ready || ended) return;
    // First connect, or a reconnect after the network dropped: the server has
    // forgotten our old connection, so rebuild from scratch.
    Object.keys(peers).forEach(teardownPeer);
    joinRoom();
  });

  socket.on('disconnect', () => {
    if (!ended) setStatus('Connection to the server lost. Reconnecting…');
  });

  socket.on('join_denied', () => {
    ended = true;
    setStatus('You cannot join this call. Returning to the appointment…');
    setTimeout(() => { window.location.href = cfg.backUrl; }, 2500);
  });

  socket.on('replaced', () => {
    ended = true;
    Object.keys(peers).forEach(teardownPeer);
    stopLocalMedia();
    showRemotePlaceholder('This call was opened in another tab or window.');
    setStatus('');
  });

  socket.on('existing_peers', async ({ peers: list }) => {
    if (!list.length) {
      setStatus('');
      broadcastMediaState();
      return;
    }
    setStatus('Connecting…');
    for (const p of list) {
      knownMeta[p.sid] = { name: p.name };
      await callPeer(p.sid);
    }
  });

  socket.on('peer_joined', ({ sid, name }) => {
    // The newcomer calls us, so we just wait for their offer.
    knownMeta[sid] = { name };
    setRemoteName(name);
    showRemotePlaceholder(name + ' is joining…');
    setStatus('Connecting…');
    broadcastMediaState();
  });

  socket.on('peer_left', ({ sid }) => {
    const name = (knownMeta[sid] && knownMeta[sid].name) || cfg.otherName;
    teardownPeer(sid);
    delete knownMeta[sid];
    showRemotePlaceholder(name + ' left the call. Waiting for them to rejoin…');
    els.muted.style.display = 'none';
    setStatus('');
  });

  socket.on('signal', async ({ sender, signal }) => {
    try {
      if (signal.type === 'offer') {
        const peer = peers[sender] || createPeer(sender);
        await peer.pc.setRemoteDescription(signal.sdp);
        await flushPending(peer);
        const answer = await peer.pc.createAnswer();
        await peer.pc.setLocalDescription(answer);
        socket.emit('signal', { target: sender, signal: { type: 'answer', sdp: peer.pc.localDescription } });
      } else if (signal.type === 'answer') {
        const peer = peers[sender];
        if (!peer) return;
        await peer.pc.setRemoteDescription(signal.sdp);
        await flushPending(peer);
      } else if (signal.type === 'candidate') {
        const peer = peers[sender];
        if (!peer) return;
        if (peer.pc.remoteDescription) {
          await peer.pc.addIceCandidate(signal.candidate).catch((e) => console.warn('ICE candidate rejected', e));
        } else {
          peer.pending.push(signal.candidate);
        }
      }
    } catch (err) {
      console.error('Signalling error', err);
      setStatus('Something went wrong connecting the call. Please leave and rejoin.');
    }
  });

  socket.on('media_state', ({ audio, video }) => {
    els.muted.style.display = audio ? 'none' : 'inline';
    if (remoteStream && remoteStream.getVideoTracks().length) {
      if (video) showRemoteVideo();
      else showRemotePlaceholder('Camera is off');
    }
  });

  socket.on('screen_share', ({ sharing }) => {
    if (sharing) setStatus('The other person is sharing their screen.', 5000);
  });

  socket.on('chat_message', ({ sid, name, message }) => {
    const mine = sid === socket.id;
    addChat(name, message, mine);
    if (!mine && !els.wrap.classList.contains('chat-open')) {
      unreadCount += 1;
      els.unread.textContent = unreadCount;
      els.unread.style.display = 'inline';
    }
  });

  /* ---------------- peer connection ---------------- */

  function createPeer(sid) {
    const pc = new RTCPeerConnection({ iceServers: cfg.iceServers });
    const peer = { pc, pending: [], timer: null };
    peers[sid] = peer;

    localStream.getTracks().forEach((t) => pc.addTrack(t, localStream));
    // If we have no camera/mic, still ask to RECEIVE that kind of media.
    ['audio', 'video'].forEach((kind) => {
      if (!localStream.getTracks().some((t) => t.kind === kind)) {
        pc.addTransceiver(kind, { direction: 'recvonly' });
      }
    });

    pc.onicecandidate = (e) => {
      if (e.candidate) socket.emit('signal', { target: sid, signal: { type: 'candidate', candidate: e.candidate } });
    };

    pc.ontrack = (e) => {
      if (!remoteStream) remoteStream = new MediaStream();
      if (!remoteStream.getTracks().includes(e.track)) remoteStream.addTrack(e.track);
      els.remoteVideo.srcObject = remoteStream;
      const name = (knownMeta[sid] && knownMeta[sid].name) || cfg.otherName;
      setRemoteName(name);
      if (remoteStream.getVideoTracks().length) showRemoteVideo();
      else showRemotePlaceholder('Audio only');
      els.remoteVideo.play().catch(() => {});
    };

    pc.onconnectionstatechange = () => {
      const state = pc.connectionState;
      if (state === 'connected') {
        clearTimeout(peer.timer);
        setStatus('Connected', 2000);
        broadcastMediaState();
      } else if (state === 'disconnected') {
        setStatus('Connection unstable…');
        clearTimeout(peer.timer);
        peer.timer = setTimeout(() => {
          if (peers[sid] && peers[sid].pc.connectionState !== 'connected') {
            setStatus('Connection lost. Ask the other person to leave and rejoin the call.');
          }
        }, 10000);
      } else if (state === 'failed') {
        setStatus('Could not connect the call. This can happen on some mobile networks. ' +
                  'Try switching between Wi-Fi and mobile data, then leave and rejoin.');
      }
    };
    return peer;
  }

  async function callPeer(sid) {
    const peer = createPeer(sid);
    const offer = await peer.pc.createOffer();
    await peer.pc.setLocalDescription(offer);
    socket.emit('signal', { target: sid, signal: { type: 'offer', sdp: peer.pc.localDescription } });
  }

  async function flushPending(peer) {
    while (peer.pending.length) {
      const c = peer.pending.shift();
      await peer.pc.addIceCandidate(c).catch((e) => console.warn('ICE candidate rejected', e));
    }
  }

  function teardownPeer(sid) {
    const peer = peers[sid];
    if (!peer) return;
    clearTimeout(peer.timer);
    peer.pc.onconnectionstatechange = null;
    peer.pc.ontrack = null;
    peer.pc.close();
    delete peers[sid];
    if (!Object.keys(peers).length) {
      remoteStream = null;
      els.remoteVideo.srcObject = null;
    }
  }

  /* ---------------- controls ---------------- */

  els.btnMic.addEventListener('click', () => {
    const t = localStream.getAudioTracks()[0];
    if (!t) return;
    t.enabled = !t.enabled;
    if (t.enabled) setBtn(els.btnMic, 'ti-microphone', 'Mute', '');
    else setBtn(els.btnMic, 'ti-microphone-off', 'Unmute', 'off');
    broadcastMediaState();
  });

  els.btnCam.addEventListener('click', () => {
    if (!cameraTrack) return;
    cameraTrack.enabled = !cameraTrack.enabled;
    if (cameraTrack.enabled) setBtn(els.btnCam, 'ti-video', 'Stop video', '');
    else setBtn(els.btnCam, 'ti-video-off', 'Start video', 'off');
    els.localOff.style.display = cameraTrack.enabled ? 'none' : 'flex';
    broadcastMediaState();
  });

  function replaceOutgoingVideo(track) {
    Object.values(peers).forEach(({ pc }) => {
      const sender = pc.getSenders().find((s) => s.track && s.track.kind === 'video');
      if (sender) sender.replaceTrack(track).catch((e) => console.warn('replaceTrack failed', e));
    });
  }

  async function startShare() {
    try {
      screenStream = await navigator.mediaDevices.getDisplayMedia({ video: true });
    } catch (e) { return; } // person cancelled the picker
    const track = screenStream.getVideoTracks()[0];
    track.onended = stopShare;
    replaceOutgoingVideo(track);
    els.localVideo.srcObject = screenStream;
    els.localBox.classList.add('sharing');
    setBtn(els.btnShare, 'ti-screen-share-off', 'Stop sharing', 'on');
    socket.emit('screen_share', { sharing: true });
  }

  function stopShare() {
    if (!screenStream) return;
    screenStream.getTracks().forEach((t) => t.stop());
    screenStream = null;
    replaceOutgoingVideo(cameraTrack);
    els.localVideo.srcObject = localStream;
    els.localBox.classList.remove('sharing');
    setBtn(els.btnShare, 'ti-screen-share', 'Share screen', '');
    socket.emit('screen_share', { sharing: false });
  }

  els.btnShare.addEventListener('click', () => (screenStream ? stopShare() : startShare()));

  els.btnChat.addEventListener('click', () => {
    els.wrap.classList.toggle('chat-open');
    if (els.wrap.classList.contains('chat-open')) {
      unreadCount = 0;
      els.unread.style.display = 'none';
      els.input.focus();
      els.msgs.scrollTop = els.msgs.scrollHeight;
    }
  });

  els.form.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = els.input.value.trim();
    if (!text) return;
    socket.emit('chat_message', { message: text });
    els.input.value = '';
  });

  function addChat(name, message, mine) {
    const row = document.createElement('div');
    row.className = 'vr-msg' + (mine ? ' mine' : '');
    const who = document.createElement('div');
    who.className = 'who';
    who.textContent = mine ? 'You' : name;
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.textContent = message;
    row.appendChild(who);
    row.appendChild(bubble);
    els.msgs.appendChild(row);
    els.msgs.scrollTop = els.msgs.scrollHeight;
  }

  function stopLocalMedia() {
    if (screenStream) screenStream.getTracks().forEach((t) => t.stop());
    if (localStream) localStream.getTracks().forEach((t) => t.stop());
  }

  function leave() {
    ended = true;
    try { socket.emit('leave'); } catch (e) { /* page is closing anyway */ }
    Object.keys(peers).forEach(teardownPeer);
    stopLocalMedia();
  }

  els.btnHangup.addEventListener('click', () => {
    leave();
    window.location.href = cfg.backUrl;
  });

  // Release the camera light if the tab is closed or navigated away.
  window.addEventListener('pagehide', leave);

  init();
})();
