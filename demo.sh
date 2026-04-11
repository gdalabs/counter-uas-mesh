#!/bin/zsh
# Counter-UAS Mesh — Full Demo Launcher
# Usage: ./demo.sh
# Then open http://localhost:8090 and start recording

cd "$(dirname "$0")"

# Kill any existing processes
pkill -f "sensor.py|interceptor.py|threat_sim.py|observer.py" 2>/dev/null
sleep 1

echo "Starting Counter-UAS Mesh demo..."

# FoxMQ broker
./foxmq run --secret-key-file=foxmq.d/key_0.pem --allow-anonymous-login &>/dev/null &
sleep 2

# Observer dashboard
PYTHONUNBUFFERED=1 python3 observer.py &>/dev/null &
sleep 1

# Sensors (triangle formation)
PYTHONUNBUFFERED=1 python3 sensor.py --id S1 --pos 0,0 &>/dev/null &
PYTHONUNBUFFERED=1 python3 sensor.py --id S2 --pos 100,0 &>/dev/null &
PYTHONUNBUFFERED=1 python3 sensor.py --id S3 --pos 50,87 &>/dev/null &

# Interceptors
PYTHONUNBUFFERED=1 python3 interceptor.py --id I1 --pos 30,30 &>/dev/null &
PYTHONUNBUFFERED=1 python3 interceptor.py --id I2 --pos 70,30 &>/dev/null &

sleep 3
echo "All nodes online. Dashboard: http://localhost:8090"
echo ""
echo "Open dashboard in browser → Start screen recording"
echo "Press ENTER to launch 3 threats..."
read

# Launch threats
PYTHONUNBUFFERED=1 python3 threat_sim.py --count 3 --speed 2

echo ""
echo "Demo complete. Stop recording."
echo "Press ENTER to cleanup..."
read

pkill -f "sensor.py|interceptor.py|threat_sim.py|observer.py|foxmq" 2>/dev/null
echo "Cleaned up."
