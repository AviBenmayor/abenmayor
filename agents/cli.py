#!/usr/bin/env python3
"""
GTM Executive Assistant — CrewAI multi-agent system

Usage:
  python cli.py brief                          # Morning briefing (news + priorities + email)
  python cli.py research <company>             # Prospect research + outreach draft
  python cli.py research <company> --contact "Name, Title"
  python cli.py content <topic>                # LinkedIn post (default)
  python cli.py content <topic> --format newsletter
  python cli.py content <topic> --format thread
"""
import sys
import argparse
from crews import run_morning_brief, run_prospect_research, run_content_generator


def main():
    parser = argparse.ArgumentParser(description="GTM Executive Assistant")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("brief", help="Generate and email morning briefing")

    research_parser = subparsers.add_parser("research", help="Research a prospect company")
    research_parser.add_argument("company", help="Company name to research")
    research_parser.add_argument("--contact", default="", help="Specific contact name and title")

    content_parser = subparsers.add_parser("content", help="Generate thought leadership content")
    content_parser.add_argument("topic", help="Topic or angle for the content")
    content_parser.add_argument(
        "--format",
        choices=["linkedin", "newsletter", "thread"],
        default="linkedin",
        help="Content format (default: linkedin)",
    )

    args = parser.parse_args()

    if args.command == "brief":
        print("Running morning briefing crew...")
        result = run_morning_brief()

    elif args.command == "research":
        print(f"Researching {args.company}...")
        result = run_prospect_research(args.company, args.contact)

    elif args.command == "content":
        print(f"Generating {args.format} content on: {args.topic}")
        result = run_content_generator(args.topic, args.format)

    print("\n" + "=" * 60)
    print(result)


if __name__ == "__main__":
    main()
