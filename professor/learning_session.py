"""
Learning Session Module - Interactive Socratic teaching with GPT.

This module provides an interactive learning experience where GPT:
1. Teaches concepts using the Socratic method
2. Tests understanding before providing answers
3. Logs learned concepts to Notion with spaced repetition
"""
from openai import OpenAI
from datetime import datetime
from typing import Optional
import config
from clients.notion_client import NotionClient
from pipeline.spaced_repetition import SpacedRepetition


class LearningSession:
    """Manages an interactive learning session with GPT."""

    def __init__(self):
        if not config.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY required for learning sessions")

        self.client = OpenAI(api_key=config.OPENAI_API_KEY)
        self.notion = NotionClient()
        self.spaced_rep = SpacedRepetition()
        self.conversation_history = []
        self.concepts_learned = []
        self.domain = config.CURRENT_TOPIC
        self.system_prompt = ""

    def start_session(self, topic: Optional[str] = None, knowledge_level: str = "beginner"):
        """
        Start an interactive learning session.

        Args:
            topic: Specific topic to learn (defaults to CURRENT_TOPIC)
            knowledge_level: beginner, intermediate, or advanced
        """
        self.domain = topic or config.CURRENT_TOPIC

        self.system_prompt = f"""You are an expert teacher using the Socratic method to help someone become genuinely knowledgeable in {self.domain}.

Your approach:
1. ALWAYS ask a question to test understanding BEFORE giving new information
2. Build on what the learner gets right, correct what they get wrong
3. After explaining a concept, provide a verification question they should be able to answer
4. Keep concepts atomic - one idea at a time

When teaching a concept, structure it as:
- What the concept is (clear explanation)
- Why it matters
- Common misconceptions
- One test question to verify understanding

The learner's current level: {knowledge_level}

Start by giving 3-5 mental models (frameworks) that experts use to think about problems in this domain. Ask a question after each to test if they grasp it.

After each concept you teach, output a special marker for logging:
[CONCEPT_LOG]
Topic: <concept name>
Explanation: <clear explanation>
Why it matters: <significance>
Test question: <question to verify understanding>
[/CONCEPT_LOG]

Be conversational but rigorous. The goal is genuine understanding, not just exposure."""

        print(f"\n{'='*60}")
        print(f"  LEARNING SESSION: {self.domain}")
        print(f"  Level: {knowledge_level}")
        print(f"{'='*60}")
        print("\nType 'quit' to end session, 'log' to save concepts to Notion")
        print("Type 'review' to see concepts learned this session\n")

        # Initial prompt to get started
        initial_prompt = f"""I'm ready to learn about {self.domain}.

My current knowledge: {self._get_knowledge_description(knowledge_level)}

Start by giving me the conceptual foundation - the 3-5 mental models that experts use to think about problems in this field. Don't give me facts yet - give me frameworks."""

        self.conversation_history.append({
            "role": "user",
            "content": initial_prompt
        })

        # Get initial response
        response = self._get_gpt_response()
        print(f"\nGPT: {response}\n")

        # Extract any concepts from initial response
        self._extract_and_store_concepts(response)

        # Main conversation loop
        self._run_conversation_loop()

    def _get_knowledge_description(self, level: str) -> str:
        """Get description of knowledge level for prompt."""
        levels = {
            "beginner": "I'm new to this. I've heard some terms but don't really understand the fundamentals.",
            "intermediate": "I have some familiarity with the basics but lack depth. I can follow conversations but can't contribute original insights.",
            "advanced": "I understand the core concepts but want to fill gaps and develop expert-level intuition."
        }
        return levels.get(level, levels["beginner"])

    def _get_gpt_response(self) -> str:
        """Get a response from GPT."""
        messages = [{"role": "system", "content": self.system_prompt}] + self.conversation_history
        response = self.client.chat.completions.create(
            model="gpt-4o",
            max_tokens=2000,
            messages=messages
        )
        assistant_message = response.choices[0].message.content
        self.conversation_history.append({
            "role": "assistant",
            "content": assistant_message
        })
        return assistant_message

    def _extract_and_store_concepts(self, response: str):
        """Extract concept logs from Claude's response and store them."""
        import re
        pattern = r'\[CONCEPT_LOG\](.*?)\[/CONCEPT_LOG\]'
        matches = re.findall(pattern, response, re.DOTALL)

        for match in matches:
            concept = self._parse_concept(match)
            if concept:
                self.concepts_learned.append(concept)
                print(f"  📚 Concept logged: {concept.get('topic', 'Unknown')}")

    def _parse_concept(self, text: str) -> dict:
        """Parse concept text into structured data."""
        lines = text.strip().split('\n')
        concept = {
            'domain': self.domain,
            'confidence': 'Low',
            'times_reviewed': 0,
            'last_reviewed': datetime.now().strftime('%Y-%m-%d'),
            'next_review': self.spaced_rep.calculate_next_review(0).strftime('%Y-%m-%d')
        }

        for line in lines:
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip().lower().replace(' ', '_')
                value = value.strip()
                if key == 'topic':
                    concept['topic'] = value
                elif key == 'explanation':
                    concept['explanation'] = value
                elif key == 'why_it_matters':
                    concept['why_it_matters'] = value
                elif key == 'test_question':
                    concept['test_question'] = value

        return concept if 'topic' in concept else None

    def _run_conversation_loop(self):
        """Run the main conversation loop."""
        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n\nSession ended.")
                break

            if not user_input:
                continue

            if user_input.lower() == 'quit':
                self._end_session()
                break

            if user_input.lower() == 'log':
                self._save_concepts_to_notion()
                continue

            if user_input.lower() == 'review':
                self._show_session_summary()
                continue

            # Add user message to history
            self.conversation_history.append({
                "role": "user",
                "content": user_input
            })

            # Get GPT's response
            response = self._get_gpt_response()
            print(f"\nGPT: {response}\n")

            # Extract any new concepts
            self._extract_and_store_concepts(response)

    def _save_concepts_to_notion(self):
        """Save learned concepts to Notion."""
        if not self.concepts_learned:
            print("No concepts to save yet.")
            return

        print(f"\nSaving {len(self.concepts_learned)} concepts to Notion...")

        for concept in self.concepts_learned:
            # Format for Notion
            article_format = {
                'title': concept.get('topic', 'Unknown'),
                'summary': concept.get('explanation', ''),
                'url': '',
                'author': 'Learning Session',
                'source': 'professor'
            }
            self.notion.create_page(article_format, 0.5)  # Low initial confidence

        print(f"✅ Saved {len(self.concepts_learned)} concepts to Notion")

    def _show_session_summary(self):
        """Show summary of concepts learned this session."""
        print(f"\n{'='*40}")
        print(f"  SESSION SUMMARY")
        print(f"  Domain: {self.domain}")
        print(f"  Concepts learned: {len(self.concepts_learned)}")
        print(f"{'='*40}")

        for i, concept in enumerate(self.concepts_learned, 1):
            print(f"\n{i}. {concept.get('topic', 'Unknown')}")
            if concept.get('explanation'):
                print(f"   {concept.get('explanation')[:100]}...")
            if concept.get('test_question'):
                print(f"   ❓ {concept.get('test_question')}")

        print()

    def _end_session(self):
        """End the session and offer to save."""
        print(f"\n{'='*40}")
        print("  SESSION COMPLETE")
        print(f"{'='*40}")
        print(f"Concepts learned: {len(self.concepts_learned)}")

        if self.concepts_learned:
            save = input("\nSave concepts to Notion? (y/n): ").strip().lower()
            if save == 'y':
                self._save_concepts_to_notion()

        print("\nGoodbye! Keep learning. 📚")


def deep_dive(topic: str):
    """Start a deep dive on a specific concept using Socratic method."""
    if not config.OPENAI_API_KEY:
        print("Error: OPENAI_API_KEY required for deep dives")
        return

    client = OpenAI(api_key=config.OPENAI_API_KEY)

    system_prompt = f"""You are an expert teacher using the Socratic method for a deep dive on: {topic}

Your approach:
1. First, ASK the learner what their current mental model is
2. Build on correct understanding, gently correct misconceptions
3. Go deep enough that they could:
   - Explain it to a smart non-expert
   - Identify when someone is wrong about it
   - Know what experts disagree about

After each exchange, consider logging a concept:
[CONCEPT_LOG]
Topic: <concept name>
Explanation: <explanation>
Why it matters: <significance>
Test question: <verification question>
[/CONCEPT_LOG]

Start by asking what they currently understand about {topic}."""

    print(f"\n{'='*60}")
    print(f"  DEEP DIVE: {topic}")
    print(f"{'='*60}")
    print("\nType 'quit' to end\n")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"I want to go deep on {topic}. Start with testing what I know."}
    ]

    # Start with GPT asking about current understanding
    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=1500,
        messages=messages
    )

    assistant_response = response.choices[0].message.content
    print(f"GPT: {assistant_response}\n")
    messages.append({"role": "assistant", "content": assistant_response})

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nDeep dive ended.")
            break

        if user_input.lower() == 'quit':
            break

        messages.append({"role": "user", "content": user_input})

        response = client.chat.completions.create(
            model="gpt-4o",
            max_tokens=1500,
            messages=messages
        )

        assistant_response = response.choices[0].message.content
        messages.append({"role": "assistant", "content": assistant_response})
        print(f"\nGPT: {assistant_response}\n")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        topic = " ".join(sys.argv[1:])
        deep_dive(topic)
    else:
        session = LearningSession()
        session.start_session()
