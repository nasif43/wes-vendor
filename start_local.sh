#!/bin/bash
# Starts both the FastAPI app and pgAdmin4 simultaneously

echo "Starting local environment..."

# 1. Start the FastAPI backend
if [ -d "venv" ]; then
    source venv/bin/activate
    export DATABASE_URL="postgresql+asyncpg://wes_user:changeme@localhost:5432/wes_vendor_local"
    echo "Starting FastAPI on port 8000..."
    uvicorn app.main:app --reload --port 8000 &
    APP_PID=$!
    deactivate
else
    echo "Error: venv not found. Please run ./local_setup.sh first."
    exit 1
fi

# 2. Start pgAdmin4
if [ -d "pgadmin_env" ]; then
    source pgadmin_env/bin/activate
    echo "Starting pgAdmin4 on port 5050..."
    pgadmin4 &
    PGADMIN_PID=$!
    deactivate
else
    echo "Error: pgadmin_env not found. Please run ./local_setup.sh first."
    kill $APP_PID
    exit 1
fi

echo ""
echo "================================================="
echo "All services are running!"
echo "App is available at:      http://localhost:8000"
echo "pgAdmin is available at:  http://localhost:5050"
echo "pgAdmin Login:            admin@local / admin"
echo "================================================="
echo "Press Ctrl+C to stop both services."
echo ""

# 3. Handle graceful shutdown when user presses Ctrl+C
trap "echo -e '\nShutting down services...'; kill $APP_PID $PGADMIN_PID 2>/dev/null; wait $APP_PID $PGADMIN_PID 2>/dev/null; echo 'Done.'; exit" SIGINT SIGTERM

# Wait indefinitely until Ctrl+C is pressed
wait
