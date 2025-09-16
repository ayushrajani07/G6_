#!/bin/bash
# G6 Platform Deployment Script

set -e

echo "🚀 G6 Platform Deployment"
echo "=========================="

# Check Python version
python_version=$(python --version 2>&1 | cut -d' ' -f2)
echo "Python version: $python_version"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Create necessary directories
echo "Creating data directories..."
mkdir -p data/csv/{overview,options,overlay}
mkdir -p .cache
mkdir -p logs

# Copy environment template if .env doesn't exist
if [ ! -f ".env" ]; then
    echo "Creating environment file from template..."
    cp g6_reorganized/config/environment.template .env
    echo "⚠️  Please edit .env with your actual credentials!"
fi

# Check configuration
echo "Validating configuration..."
cd g6_reorganized
python -c "
from config.config_loader import ConfigLoader
try:
    config = ConfigLoader.load_config()
    issues = ConfigLoader.validate_config(config)
    if issues:
        print('Configuration issues:')
        for issue in issues:
            print(f'  - {issue}')
    else:
        print('✅ Configuration valid')
except Exception as e:
    print(f'Configuration error: {e}')
"

echo ""
echo "✅ Deployment complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env with your Kite Connect credentials"
echo "2. Customize config/g6_config.json if needed"  
echo "3. Run: source venv/bin/activate && cd g6_reorganized && python main.py"
echo ""
echo "Monitor at: http://localhost:9108/metrics"
