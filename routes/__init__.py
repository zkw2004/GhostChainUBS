from flask import Flask

app = Flask(__name__)
import routes.ghost_chains  # noqa: E402,F401
