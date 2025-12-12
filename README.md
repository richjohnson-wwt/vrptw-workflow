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