#!/bin/bash

# ==============================================================================
# 🚀 ADVANCED RECOMMENDER AI SYSTEM - QUICK START GUIDE
# ==============================================================================

echo "🚀 Advanced Recommender AI System - Quick Start"
echo "==============================================="
echo ""

# ==============================================================================
# OPTION 1: RUN WITH DOCKER (Recommended)
# ==============================================================================

run_docker_advanced() {
    echo "📦 Starting with Docker (Advanced Profile)..."
    echo "⏳ This will take 5-7 minutes on first run..."
    echo ""
    
    docker-compose --profile advanced up recommender-ai-service
    
    echo ""
    echo "✅ Service ready at http://localhost:8011"
    echo "📊 Dashboard: http://localhost:8011/api/recommendations/health"
}

# ==============================================================================
# OPTION 2: RUN LOCALLY
# ==============================================================================

run_local() {
    echo "🛠️  Setting up local environment..."
    
    # Check Python
    if ! command -v python3 &> /dev/null; then
        echo "❌ Python 3 not found!"
        exit 1
    fi
    
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    echo "✓ Python $PYTHON_VERSION"
    
    # Create venv
    if [ ! -d "venv" ]; then
        echo "📦 Creating virtual environment..."
        python3 -m venv venv
    fi
    
    # Activate venv
    source venv/bin/activate 2>/dev/null || . venv/Scripts/activate
    
    # Install dependencies
    echo "📥 Installing dependencies..."
    pip install -q -r recommender-ai-service/requirements.txt
    
    # Initialize database
    cd recommender-ai-service
    echo ""
    echo "🚀 Initializing Advanced Recommender System..."
    echo "⏳ Generating dataset..."
    echo "⏳ Training deep learning model..."
    echo "⏳ Populating database..."
    python init_recommender_advanced.py
    
    echo ""
    echo "✅ Setup complete!"
    echo "🚀 Starting service..."
    uvicorn app:app --reload --port 8000
}

# ==============================================================================
# OPTION 3: JUST GENERATE DATA
# ==============================================================================

generate_data_only() {
    echo "📊 Generating dataset only (no model training)..."
    
    cd recommender-ai-service
    python dataset_generator.py
    
    echo ""
    echo "📁 Generated files:"
    echo "  • books.json       (2000 books)"
    echo "  • customers.json   (300 customers)"
    echo "  • events.json      (5000+ interactions)"
}

# ==============================================================================
# OPTION 4: TRAIN MODEL ONLY
# ==============================================================================

train_model_only() {
    echo "🧠 Training deep learning model..."
    
    cd recommender-ai-service
    python -c "from deep_learning_model import train_and_save_model; import json; import subprocess
events = []
try:
    with open('events.json') as f:
        events = json.load(f)
except:
    print('No events.json found. Generate with dataset_generator.py first.')
    exit(1)
train_and_save_model(events)"
}

# ==============================================================================
# OPTION 5: SHOW STATISTICS
# ==============================================================================

show_stats() {
    echo "📊 System Statistics"
    echo "===================="
    echo ""
    
    # Database stats
    if command -v mysql &> /dev/null; then
        echo "📚 Books in database:"
        mysql -h 127.0.0.1 -u root -p123456 recommender_db -e \
            "SELECT COUNT(*) as total, COUNT(DISTINCT category) as categories FROM recommender_books;"
        
        echo ""
        echo "👥 Customers:"
        mysql -h 127.0.0.1 -u root -p123456 recommender_db -e \
            "SELECT COUNT(*) as total_customers, AVG(purchase_count) as avg_purchases FROM recommender_user_preferences;"
        
        echo ""
        echo "📊 Interactions:"
        mysql -h 127.0.0.1 -u root -p123456 recommender_db -e \
            "SELECT event_type, COUNT(*) as count FROM interaction_history GROUP BY event_type;"
        
        echo ""
        echo "🤖 Model Info:"
        mysql -h 127.0.0.1 -u root -p123456 recommender_db -e \
            "SELECT model_name, model_version, training_samples, auc_score FROM model_metadata ORDER BY created_at DESC LIMIT 1;"
    else
        echo "MySQL client not found. Run service first to populate database."
    fi
}

# ==============================================================================
# OPTION 6: HEALTH CHECK
# ==============================================================================

health_check() {
    echo "🏥 Health Check"
    echo "==============="
    echo ""
    
    echo "📡 Checking service health..."
    response=$(curl -s -w "\n%{http_code}" http://localhost:8011/api/recommendations/health)
    
    status_code=$(echo "$response" | tail -1)
    body=$(echo "$response" | head -1)
    
    if [ "$status_code" == "200" ]; then
        echo "✅ Service is running!"
        echo ""
        echo "Response:"
        echo "$body" | python -m json.tool 2>/dev/null || echo "$body"
    else
        echo "❌ Service not responding (HTTP $status_code)"
        echo "Make sure service is running at http://localhost:8011"
    fi
}

# ==============================================================================
# OPTION 7: TEST API
# ==============================================================================

test_api() {
    echo "🧪 Testing Recommendation API"
    echo "=============================="
    echo ""
    
    echo "📤 Sending test request..."
    curl -X POST http://localhost:8011/api/recommendations \
        -H "Content-Type: application/json" \
        -d '{
            "customer_id": 1,
            "viewed_book_ids": [1, 2, 3],
            "purchased_book_ids": [1]
        }' \
        -s | python -m json.tool 2>/dev/null || echo "Service not responding"
}

# ==============================================================================
# MAIN MENU
# ==============================================================================

if [ "$1" == "docker" ]; then
    run_docker_advanced
elif [ "$1" == "local" ]; then
    run_local
elif [ "$1" == "data" ]; then
    generate_data_only
elif [ "$1" == "train" ]; then
    train_model_only
elif [ "$1" == "stats" ]; then
    show_stats
elif [ "$1" == "health" ]; then
    health_check
elif [ "$1" == "test" ]; then
    test_api
else
    echo "📋 Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  docker   - Run with Docker (recommended)"
    echo "  local    - Run locally with Python"
    echo "  data     - Generate dataset only"
    echo "  train    - Train model only"
    echo "  stats    - Show database statistics"
    echo "  health   - Health check"
    echo "  test     - Test recommendation API"
    echo ""
    echo "Examples:"
    echo "  $0 docker      # Start with Docker"
    echo "  $0 local       # Start locally"
    echo "  $0 health      # Check if service is running"
    echo "  $0 test        # Test API"
    echo ""
    echo "📚 For more info, see README_ADVANCED.md"
fi
