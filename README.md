# VRPTW Workflow

## Setup

    uv venv venv
    source venv/bin/activate
    uv sync
    uv add pandas xlrd openpyxl scikit-learn

    sqlite3 -readonly -cmd ".headers on" -cmd ".mode box" ~/Documents/VRPTW/.cache/nominatim.sqlite "SELECT * FROM addresses LIMIT 50;"