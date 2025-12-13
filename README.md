# VRPTW Workflow

## Setup

    uv venv venv
    source venv/bin/activate
    uv sync
    uv add pandas xlrd openpyxl scikit-learn ortools folium

    sqlite3 -readonly -cmd ".headers on" -cmd ".mode box" ~/Documents/VRPTW/.cache/nominatim.sqlite "SELECT * FROM addresses LIMIT 50;"


    sqlite3 -readonly -cmd ".headers on" -cmd ".mode box" ~/Documents/VRPTW/.cache/nominatim.sqlite " SELECT id, normalized_address, latitude, longitude, display_name, updated_at FROM addresses WHERE normalized_address LIKE '%211 S 18th%' OR normalized_address LIKE '%10630 Parallel%' "

    sqlite3 -readonly -cmd ".headers on" -cmd ".mode box" ~/Documents/VRPTW/.cache/nominatim.sqlite " SELECT id, normalized_address, latitude, longitude, display_name, updated_at FROM addresses WHERE normalized_address LIKE '%211 S 18th%' OR normalized_address LIKE '%10630 Parallel%' "

    sqlite3 ~/Documents/VRPTW/.cache/nominatim.sqlite " DELETE FROM addresses WHERE normalized_address LIKE '%211 S 18th%' OR normalized_address LIKE '%10630 Parallel%' "


## Code Cleanup

    uv add --dev ruff autoflake isort black
    uv run autoflake --in-place --remove-all-unused-imports --remove-unused-variables --exclude .venv --recursive .
    uv run isort .
    uv run ruff check . --fix
    uv run black .
    uv run -m app