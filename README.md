# VRPTW Workflow

## Setup

    uv venv venv
    source venv/bin/activate
    uv sync
    uv add pandas xlrd openpyxl scikit-learn ortools folium pyyaml

    
## Cache useful commands

    sqlite3 -readonly -cmd ".headers on" -cmd ".mode box" ~/Documents/VRPTW/.cache/nominatim.sqlite "SELECT * FROM addresses LIMIT 50;"


    sqlite3 -readonly -cmd ".headers on" -cmd ".mode box" ~/Documents/VRPTW/.cache/nominatim.sqlite " SELECT id, normalized_address, latitude, longitude, display_name, updated_at FROM addresses WHERE normalized_address LIKE '%211 S 18th%' OR normalized_address LIKE '%10630 Parallel%' "

    sqlite3 -readonly -cmd ".headers on" -cmd ".mode box" ~/Documents/VRPTW/.cache/nominatim.sqlite " SELECT id, normalized_address, latitude, longitude, display_name, updated_at FROM addresses WHERE normalized_address LIKE '%211 S 18th%' OR normalized_address LIKE '%10630 Parallel%' "

    sqlite3 ~/Documents/VRPTW/.cache/nominatim.sqlite " DELETE FROM addresses WHERE normalized_address LIKE '%211 S 18th%' OR normalized_address LIKE '%10630 Parallel%' "

    select normalized_address, latitude, longitude from addresses where latitude is null or longitude is null;

    delete from addresses where latitude is null or longitude is null;


## Code Cleanup

    uv add --dev ruff autoflake isort black
    uv run autoflake --in-place --remove-all-unused-imports --remove-unused-variables --exclude .venv --recursive .
    uv run isort .
    uv run ruff check . --fix
    uv run black .
    uv run -m app

## Nominatim Manual test

     curl -G "https://nominatim.openstreetmap.org/search" \
        --data-urlencode "street=3146 PEACHTREE ROAD N.E." \
        --data-urlencode "city=ATLANTA" \
        --data-urlencode "state=GA" \
        --data-urlencode "country=USA" \
        --data-urlencode "format=jsonv2" \
        -H "User-Agent: VRPTW-Workflow/0.1 (contact: rich.johnson@wwt.com)" | jq

nominatim:full — matched using the full normalized address string: "address, city, state ZIP, USA" (most precise; typically door/building-level if OSM has it).
nominatim:city-state — matched using only "city, ST" (a coarse fallback; often returns a city centroid). These are more likely to produce duplicated coordinates across different addresses in the same city.
nominatim:no-zip — address without ZIP ("address, city, ST, USA").
nominatim:territory — address with a US territory full name substituted (if applicable).

## TEMP NOTE - From Cascade on Friday, Dec 12
Quick recap of what’s ready:

VRPTW state-wide solve by default with Avg stops/day metric
“View on Map” saves next to clustered.csv and auto-opens
Parse sanitizes addresses (no “nan”); cache SQL in README
Layouts fixed so subtabs fill space
Codebase cleaned (ruff/autoflake/isort/black); cleanup commands in README

Potential next steps for Monday:

Structured Nominatim queries + duplicate geocode detection
Arrival/start times in results and CSV exports
Auto-K weighted clustering (balance by service minutes)
Optional OSRM travel times for better realism
Have a great weekend!