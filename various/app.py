"""A minimal Flask application for Posit Connect."""

from flask import Flask, render_template

app = Flask(__name__)


@app.get("/")
def home():
    """Render the sample application."""
    return render_template("index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
