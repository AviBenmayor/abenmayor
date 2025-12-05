"""
Command-Line Interface for Arbitrage Scanner

Usage:
    python cli.py discover    # Run market discovery
    python cli.py monitor     # Run price monitor
    python cli.py run-all     # Run discovery then monitor
"""
import sys
from dotenv import load_dotenv
import market_discovery
import price_monitor

# Load environment variables from .env file
load_dotenv()


def print_usage():
    """Print CLI usage information."""
    print("Arbitrage Scanner CLI")
    print("=" * 60)
    print("Usage:")
    print("  python cli.py discover    # Run market discovery")
    print("  python cli.py monitor     # Run price monitor")
    print("  python cli.py run-all     # Run discovery then monitor")
    print("=" * 60)


def main():
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "discover":
        market_discovery.discover_markets()
    
    elif command == "monitor":
        price_monitor.monitor_loop()
    
    elif command == "run-all":
        print("Running market discovery...")
        market_discovery.discover_markets()
        print("\nStarting price monitor...")
        price_monitor.monitor_loop()
    
    else:
        print(f"Unknown command: {command}")
        print_usage()
        sys.exit(1)


if __name__ == "__main__":
    main()
