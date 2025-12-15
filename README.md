# VRPTW Workflow

    WorkspaceTab: Add/Select Client, Add/Select workspace
    ParseTab: Excel -> addresses.csv
    GeocodeTab: addresses.csv -> geocode_tab.py -> geocoded.csv
    ClusterTab: geocoded.csv -> clustered.csv
    VRPTWTab: clustered.csv -> solve.py -> solution.csv
    

## Setup

    uv venv venv
    source venv/bin/activate
    uv sync
    uv add pandas xlrd openpyxl scikit-learn ortools folium pyyaml

    
## Tests

     # run tests
     uv run pytest
     
     # run tests verbosely
     uv run pytest -v
     
     # run specific test
     uv run pytest tests/test_geocoding_cache.py

     # run tests verbosely with short traceback
     uv run pytest -v --tb=short



## Cache useful commands

    sqlite3 ~/Documents/VRPTW/.cache/nominatim.sqlite

    SELECT 
        normalized_address,
        source,
        updated_at
    FROM addresses 
    WHERE latitude IS NULL AND longitude IS NULL
    ORDER BY updated_at DESC;

To see failed entries grouped by state:

    SELECT 
        SUBSTR(normalized_address, 
            INSTR(normalized_address, ', ') + 2,
            2) AS state,
        COUNT(*) as failed_count
    FROM addresses 
    WHERE latitude IS NULL AND longitude IS NULL
    GROUP BY state
    ORDER BY failed_count DESC;

To see the full details of failed entries:

    SELECT 
        id,
        normalized_address,
        display_name,
        source,
        updated_at
    FROM addresses 
    WHERE latitude IS NULL AND longitude IS NULL
    LIMIT 20;

If you want to run it as a one-liner from the terminal:

    sqlite3 ~/Documents/VRPTW/.cache/nominatim.sqlite "SELECT normalized_address, source, updated_at FROM addresses WHERE latitude IS NULL AND longitude IS NULL ORDER BY updated_at DESC;"

To see the breakdown:
    
    sqlite3 ~/Documents/VRPTW/.cache/nominatim.sqlite "SELECT 
        CASE 
            WHEN latitude IS NULL THEN 'Failed'
            ELSE 'Successful'
        END as status,
        COUNT(*) as count
    FROM addresses
    GROUP BY status;"

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
        --data-urlencode "3500 SE Frank Phillips, 2nd floor" \
        --data-urlencode "city=Bartlesville" \
        --data-urlencode "state=OK" \
        --data-urlencode "country=USA" \
        --data-urlencode "format=jsonv2" \
        -H "User-Agent: VRPTW-Workflow/0.1 (contact: rich.johnson@wwt.com)" | jq

nominatim:full — matched using the full normalized address string: "address, city, state ZIP, USA" (most precise; typically door/building-level if OSM has it).
nominatim:city-state — matched using only "city, ST" (a coarse fallback; often returns a city centroid). These are more likely to produce duplicated coordinates across different addresses in the same city.
nominatim:no-zip — address without ZIP ("address, city, ST, USA").
nominatim:territory — address with a US territory full name substituted (if applicable).

