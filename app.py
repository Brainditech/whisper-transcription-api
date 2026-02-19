from flask import Flask
from blueprints.transcribe import transcribe_bp

def create_app():
    app = Flask(__name__)
    # Set maximum upload size (e.g., 500 MB)
    app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
    app.register_blueprint(transcribe_bp)
    return app

app = create_app()

if __name__ == "__main__":
    from waitress import serve
    print("Starting Waitress server on http://0.0.0.0:8000")
    serve(app, host="0.0.0.0", port=8000)