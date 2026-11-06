from app import create_app, socketio
import os

app = create_app()

if __name__ == '__main__':
    db_url = os.getenv('DATABASE_URL', 'not set')
    print()
    print('=' * 50)
    print(' MedLink Uganda')
    print('=' * 50)
    print(f' Database : {db_url[:40]}')
    print(f' URL : http://localhost:5000')
    print(f' Search : http://localhost:5000/search')
    print('=' * 50)
    print()
    socketio.run(app, debug=True, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
