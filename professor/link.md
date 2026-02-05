The Complete Guide: How to Learn Anything. For Good. 
It's my job to learn things. Fast.
Not just learn things topically. I need to become an expert on an entire industry in under 30 minutes.
I run a consulting company, so my entire job is to walk into rooms where everyone knows more than me—and leave with them trusting my judgment.
Last month it was pharmaceutical supply chains. Before that, carbon credit markets. Next week it's semiconductor manufacturing.
The traditional path to expertise takes years. Reading books, taking courses, accumulating experience through trial and error. I don't have years. I have days. Sometimes hours.
Most people fake it. They learn just enough vocabulary to sound credible, then hope nobody asks a hard follow-up question.
I don't fake it anymore. I actually learn the material—deeply enough to have original insights, catch mistakes in client documents, and ask questions that make domain experts pause.
I do this with Claude Code and Notion.
Why This Isn't Just "Asking AI Questions"
You could ask ChatGPT to explain pharmaceutical supply chains. You'd get a decent overview. Then you'd forget 80% of it within a week.
That's not learning. That's cramming.
Real expertise requires three things most people skip:
Spaced repetition. You need to revisit information at increasing intervals—right before you'd forget it. This is how memory consolidates from short-term to long-term storage.
Active recall. Reading something again doesn't work. You need to actively retrieve information from memory. The struggle of trying to remember is what builds durable knowledge.
Connected understanding. Isolated facts don't create expertise. You need to see how concepts relate, where the exceptions are, what the experts argue about.
The insight that changed everything for me:
Claude Code can manage all three automatically.
It remembers what I've learned, when I learned it, and what I'm likely to forget. It generates daily review material calibrated to my actual knowledge state. It connects new information to what I already know.
I turned my learning process into a system. The system runs whether I feel motivated or not.
The Outcome: What You're Building
Here's what the system produces:
A personal knowledge base that grows with every conversation. Every question you ask, every concept you learn, every connection you make—it all gets captured in Notion. Structured. Searchable. Connected.
A daily "newsletter" written specifically for your brain. Each morning, Claude Code queries your knowledge base, identifies what you're about to forget, and generates a custom review document. It includes the concepts you need to revisit, questions to test yourself, and connections you might have missed.
Genuine expertise in 2-3 weeks instead of 2-3 years. Not surface familiarity. Real understanding—the kind where you can explain concepts to others, spot errors in expert documents, and ask questions that reveal you actually get it.
The end state looks like this:
You wake up. You open a document Claude Code generated overnight. It says:
"Today, review: Fab Economics Model (3rd review), EUV Lithography (due today), Yield Curve dynamics (new yesterday). Test yourself on these three questions before your 2pm client call. Also: I noticed a connection between your notes on TSMC's capacity constraints and the Intel earnings you asked about last week—see synthesis below."
You spend 15 minutes with your coffee. You answer the questions. You read the synthesis. You update your confidence levels.
By the time you walk into that client meeting, you're not pretending. You've reviewed the material at scientifically-optimal intervals. You've practiced retrieving it from memory. You've seen how it connects to everything else you know.
The VP of Supply Chain asks you a curveball question. You answer it—not because you memorized a script, but because you actually understand the underlying dynamics.
That's the outcome. A system that turns you into a genuine expert, automatically, while you sleep.
The Setup
You need three things:
Claude Code — The AI that does the teaching and manages the system
Notion — The database that stores your knowledge
The Notion MCP — The connector that lets Claude Code read and write to Notion
Setting Up Notion
Create a new database called "Knowledge Base" with these properties:
Topic (Title) — The concept name
Domain (Select) — The field (e.g., "Pharma Supply Chain")
Explanation (Text) — The actual content
Last Reviewed (Date) — When you last looked at it
Next Review (Date) — When spaced repetition says to review
Confidence (Select) — Low / Medium / High
Times Reviewed (Number) — How many times you've seen it
Questions (Text) — Follow-ups you still have
Connections (Relation) — Links to related concepts
Create a second database called "Learning Sessions" with:
Date (Date) — When the session happened
Domain (Select) — What field you were studying
Concepts Covered (Relation) — Links to Knowledge Base entries
Key Insights (Text) — What clicked during this session
Open Questions (Text) — What you're still confused about
Setting Up the Notion MCP
In Claude Code, connect to Notion:
Connect to my Notion workspace. I want you to be able to
read and write to my "Knowledge Base" and "Learning Sessions" databases.
Claude will walk you through the OAuth connection. Once connected, verify:
Show me the structure of my Knowledge Base database.
Confirm you can read and write to it.
Now you have an AI that can manage your learning database directly.
The Core Workflow
Phase 1: The Learning Session
When I need to learn a new domain, I start a focused session with Claude Code.
Opening Prompt:
I'm a consultant starting a project in [DOMAIN]. I need to become
genuinely knowledgeable—not surface-level—within [TIMEFRAME].
My current knowledge: [HONEST ASSESSMENT]
Start by giving me the conceptual foundation. What are the 3-5 mental
models that experts in this field use to think about problems?
Don't give me facts yet—give me frameworks.
After each concept, log it to my Notion Knowledge Base with:
- A clear explanation
- Why it matters
- Common misconceptions
- One question I should be able to answer if I understand it
Set the confidence to "Low" and the next review date to tomorrow.
Example — Semiconductor Manufacturing:
I'm a consultant starting a project advising a semiconductor company
on supply chain resilience. I need to become genuinely knowledgeable
within 2 weeks.
My current knowledge: I understand chips go in computers. I've read
some news about TSMC and the CHIPS Act. That's about it.
Start by giving me the conceptual foundation. What are the 3-5 mental
models that experts in this field use to think about problems?
Claude's response includes frameworks like:
The Fab Economics Model: Semiconductor fabs are the most capital-intensive factories on Earth—$20B+ for a leading-edge facility. This creates a "build it and they will come" dynamic where capacity decisions are made 3-5 years before demand is known. Understanding this lag explains most supply chain crises...

Logging to Notion: "Fab Economics Model" — Domain: Semiconductors — Confidence: Low — Next Review: Tomorrow

Verification question: If a chip shortage hits in 2025, when were the capacity decisions that caused it likely made?
I answer the question. Claude corrects me or confirms. We move to the next framework.
Phase 2: Deep Dives
Once I have the frameworks, I go deep on specifics. But I don't just read—I interrogate.
Deep Dive Prompt:
Now go deeper on [SPECIFIC CONCEPT]. I want to understand it well
enough to:
1. Explain it to a smart non-expert
2. Identify when someone is wrong about it
3. Know what experts disagree about
Use the Socratic method. Ask me questions to test my understanding
before giving me more information. When I get something wrong,
explain why—don't just give me the right answer.
Log any new concepts we cover to Notion. Update my confidence level
based on how I perform.
Example:
Now go deeper on the lithography process. I've heard "EUV" mentioned
constantly but don't really understand what it is or why it matters.
Claude responds with a question first:
Before I explain EUV, let me test your existing model.

You know chips are made by putting patterns on silicon. How do you think those patterns get there? What's your mental image of the process?
I give my best guess. Claude builds on what I got right, corrects what I got wrong, then goes deeper:
Good instinct on the "printing" metaphor. You're essentially right that it's like photography. Here's where it gets interesting...

[Detailed explanation of wavelengths, resolution limits, ASML's monopoly]

Now, here's a harder question: If EUV uses 13.5nm wavelength light, and leading chips have 3nm features, how is that physically possible? Doesn't the wavelength set a limit?
This back-and-forth continues. Every concept gets logged. Every question I struggle with gets noted. My confidence levels update in real-time.
Phase 3: The Daily Newsletter
This is where the system pays off.
Every morning, I run:
Generate my daily learning newsletter.
Query my Knowledge Base for:
1. Anything with Next Review date of today or earlier
2. Any items marked Low confidence that I haven't seen in 3+ days
3. Connections between concepts I've learned in different sessions
Format as a newsletter with:
- "Review These Today" (spaced repetition items)
- "Test Yourself" (active recall questions for each)
- "Connections You Might Have Missed" (synthesis across concepts)
- "This Week's Focus" (what I should go deeper on)
After I review, update the Last Reviewed dates and calculate new
Next Review dates using spaced repetition intervals:
- First review: 1 day
- Second review: 3 days
- Third review: 7 days
- Fourth review: 14 days
- Fifth+: 30 days
If I get a question wrong, reset to 1-day interval.
Sample Daily Newsletter
Here's what Claude Code generates for me after a week of learning semiconductors:
Your Daily Learning Brief — Wednesday, January 15
Domain: Semiconductor Manufacturing | Day 8 of 14
REVIEW THESE TODAY
1. Fab Economics Model (3rd review — last seen Monday)
The $20B+ capital cost of leading-edge fabs creates a 3-5 year lag between capacity decisions and production. This lag, combined with demand volatility, explains most supply chain crises.
Test yourself: The chip shortage of 2021-2022 was partly caused by capacity decisions made in what year range? What event made those decisions look wrong in retrospect?
2. EUV Lithography (2nd review — last seen Sunday)
Extreme Ultraviolet lithography uses 13.5nm wavelength light, enabling sub-7nm chip features through multi-patterning. ASML holds a monopoly on EUV machines; each costs $150M+ and requires its own cargo plane to ship.
Test yourself: Why can't competitors replicate ASML's EUV technology, even with unlimited funding? (Hint: it's not just patents.)
3. The Yield Curve (1st review — learned yesterday)
Yield = percentage of chips on a wafer that actually work. New processes start at <50% yield and improve to >90% over 12-18 months. This "yield ramp" determines profitability more than any other factor.
Test yourself: A fab produces 1,000 chips per wafer. At 50% yield, they get 500 working chips. If each chip sells for $100 and the wafer costs $10,000 to produce, are they profitable? What yield do they need to break even?
CONNECTIONS YOU MIGHT HAVE MISSED
Your notes on "Fab Economics" and "Yield Curve" are both filed separately, but they're deeply related:
A new fab costs $20B. But that $20B bet only pays off if yields ramp fast enough. Intel's 10nm struggles weren't really a technology problem—they were a yield problem that made an already-expensive process economically unviable.
Consider: If you were advising a semiconductor company, how would you think about the risk of building a new fab? What would you want to know about their historical yield ramps?
THIS WEEK'S FOCUS
Based on your confidence scores, prioritize:
Packaging and Chiplets (Low confidence, no review scheduled) — You asked about this Monday but we didn't go deep. It's becoming central to the industry.
Geopolitical Dependencies (Medium confidence, due for reinforcement) — You understand the TSMC/Taiwan risk. Less clear on rare earth materials and gas supply chains.
Your Open Questions (from your last session):
"Why hasn't the U.S. caught up to TSMC despite CHIPS Act funding?"
"What happens to older fabs when they become obsolete?"
Ready to dive into any of these? Just tell me which.
The Question Protocol
Whenever I have a question—during client calls, reading industry reports, or random curiosity—I use Claude Code to both answer it and log it.
The Question Prompt:
Quick question about [DOMAIN]:
[YOUR QUESTION]
Answer it, then:
1. Log the answer to my Notion Knowledge Base as a new concept
2. Connect it to any related concepts already in my database
3. Note if this changes my understanding of anything I've already learned
4. Give me one follow-up question I should be able to answer in 3 days
Example:
Quick question about semiconductors:
I read that TSMC's "3nm" process isn't actually 3 nanometers.
What does the number actually mean?
Answer it, then log appropriately.
Claude responds:
Great catch—this confuses everyone, including industry analysts.

The "3nm" label is now purely a marketing term. It originally referred to the gate length of transistors, but that direct correlation broke down around the 20nm node. Today, "3nm" indicates roughly which generation of manufacturing process it is, not any physical dimension.

Actual transistor features at "3nm" might be 20-30nm. The number is meaningful only relative to previous generations: "3nm" is denser and more power-efficient than "5nm," which beat "7nm," and so on.

Logging to Knowledge Base: "Node Naming Conventions" — Connected to: "EUV Lithography," "Yield Curve" — Note: This updates your understanding of marketing vs. technical claims in the industry.

Follow-up to answer by Saturday: If the numbers don't mean physical dimensions, what metric should you use to compare chip generations? (Hint: think about what customers actually care about.)
Over time, my Knowledge Base becomes a web of interconnected concepts—with every question I've asked, every correction I needed, every synthesis I've made.
Building Your Expert Persona
After 2-3 weeks of this process, I don't just know facts. I have something more valuable: the ability to think like someone in the field.
The Expert Test Prompt:
I have a meeting with [CLIENT TYPE] in [TIMEFRAME].
Test my readiness:
1. What questions will they likely ask me?
2. What questions should I ask them to demonstrate expertise?
3. What mistakes do smart outsiders typically make in this domain?
4. What contrarian or nuanced take could I offer that would
surprise them?
Be tough. I'd rather fail here than in the meeting.
Example:
I have a meeting with a semiconductor company's VP of Supply Chain
tomorrow.
Test my readiness.
Claude responds:
Questions they'll likely ask you:
"How familiar are you with our industry?" — They're checking if they'll need to hand-hold you. You should be able to casually reference the fab economics problem, the ASML bottleneck, and yield ramp dynamics without it sounding rehearsed.
"What's your take on nearshoring fab capacity?" — This is the hot topic. They want to know if you understand why it's hard, not just that it's happening.
Questions you should ask them:
"How do you think about the yield ramp timeline for your next node—and what does that mean for your capacity commitments?" — This signals you understand the real game.
"What's your strategy if EUV machine delivery slips six months?" — Shows you know where the bottlenecks are.
Mistakes smart outsiders make:
Treating chip manufacturing like normal manufacturing (it's not— the physics is different)
Overweighting geopolitical risk while underweighting technical risk
Not understanding why "just build more fabs" isn't a solution
A nuanced take that would impress:
"The industry talks about the 'semiconductor shortage' as if it's one thing, but it was really three different shortages: leading-edge logic, mature node logic, and analog chips. Each had different causes and different solutions. I'm curious which one keeps you up at night."
Want me to drill you on any of these?
Domain Templates
I've built up prompts for different types of knowledge. Use these as starting points:
For Technical Domains
I need to understand [TECHNICAL FIELD] well enough to evaluate
vendor claims and ask intelligent questions of engineers.
I don't need to do the work myself—I need to know:
1. What the key tradeoffs are
2. What questions reveal if someone knows what they're doing
3. What the common failure modes are
4. What "good" looks like vs. "good enough" vs. "red flag"
Start with the mental models, then go deep on whatever I ask about.
Log everything to Notion for spaced repetition.
For Business/Strategy Domains
I need to understand [INDUSTRY/MARKET] well enough to advise
executives on strategic decisions.
I need:
1. The economic structure (who makes money, how, why margins are
what they are)
2. The competitive dynamics (what moats exist, what's commoditized)
3. The current disruptions (what's changing, who wins/loses)
4. The insider language (what terms signal expertise vs. novice)
Teach me to think like a long-time industry analyst.
Log everything to Notion for spaced repetition.
For Regulatory/Legal Domains
I need to understand [REGULATORY AREA] well enough to spot
compliance risks and ask the right questions of legal counsel.
I need:
1. The intent behind the regulations (what problem were they solving)
2. The key requirements (what actually matters vs. box-checking)
3. The common violations (what trips companies up)
4. The enforcement reality (what actually gets punished)
I'm not becoming a lawyer—I'm becoming dangerous enough to know
when to call one.
Log everything to Notion for spaced repetition.
Common Mistakes
Passive learning. Reading Claude's explanations without answering its questions. The struggle to recall is the learning. Don't skip it.
Skipping the newsletter. The daily review is where knowledge consolidates. Miss three days and you're back to cramming instead of learning.
Going too broad. "I need to learn supply chain" is too vague. "I need to understand pharmaceutical cold chain logistics" is actionable. Scope your domains.
Not logging questions. Every question you have is valuable. If you ask something in a client meeting and don't log it, you'll lose the insight. Make logging automatic.
Trusting your confidence. You think you know something until you're tested. Let Claude quiz you before you claim expertise.
The Compound Effect
Here's what most people don't understand about this system:
Knowledge compounds across domains.
After I learned pharmaceutical supply chains, learning semiconductor supply chains was faster—I already had mental models for demand forecasting, inventory management, and regulatory constraints. Different content, same structures.
After five or six domains, you start recognizing patterns everywhere. New industries become variations on themes you've seen before.
My Knowledge Base now has 400+ concepts across a dozen domains. They're connected. A question about one often surfaces relationships to others.
The 10th domain takes half the time of the first. The 20th domain takes a quarter.
This is what expertise actually is: pattern recognition across contexts. The system builds it automatically.
What This Doesn't Replace
AI-powered learning is powerful. It's not magic.
It doesn't replace primary experience. You can learn about surgery without being qualified to operate. Know the difference between intellectual understanding and practical skill.
It doesn't replace relationships. Domain experts are valuable not just for their knowledge but for their network, judgment, and reputation. Use this system to become a better conversation partner, not to avoid conversations.
It doesn't replace judgment. Claude can teach you what experts know. It can't teach you which experts to trust or when the consensus is wrong. That's still on you.
It doesn't replace doing the work. If your job requires producing outputs—analyses, designs, decisions—you still have to produce them. This system makes you better prepared, not exempt from execution.
Current Limitations
Notion MCP is in early days. Complex database queries sometimes fail. Start with simple structures and build complexity as you learn what works reliably.
Token limits on sessions. Very long learning sessions can hit context limits. When this happens, start a new session—Claude can read your Notion database to rebuild context.
Spaced repetition timing isn't perfect. The intervals I use (1, 3, 7, 14, 30 days) are approximations. Adjust based on what you notice about your own memory.
Claude can be wrong. Especially in specialized domains, Claude can state things confidently that aren't accurate. Cross-reference with primary sources for high-stakes information.
The system requires discipline. The newsletter only works if you review it. The knowledge base only helps if you populate it. Garbage in, garbage out.
Quick Start
Set up Notion databases. Knowledge Base and Learning Sessions, with the properties listed above.
Connect Claude Code to Notion. Use the Notion MCP and verify it can read and write.
Pick one domain. Something you need for work in the next 30 days. Specific is better than broad.
Run your first learning session. Use the framework prompt. Spend 30 minutes getting the mental models.
Generate your first newsletter tomorrow. Review it. Answer the questions. Update the database.
Ask every question through the system. Every time you're curious, use the question protocol. Log everything.
Run the newsletter daily. This is non-negotiable. The compound effect only works with consistency.
One domain. Two weeks. Then evaluate.
Quick Reference
The Stack:
Claude Code — The teacher and system manager
Notion — The knowledge database
Notion MCP — The connection between them
Database Structure:
Knowledge Base: Topic, Domain, Explanation, Last Reviewed, Next Review, Confidence, Times Reviewed, Questions, Connections
Learning Sessions: Date, Domain, Concepts Covered, Key Insights, Open Questions
Spaced Repetition Intervals:
1st review: 1 day
2nd review: 3 days
3rd review: 7 days
4th review: 14 days
5th+: 30 days
Failed recall: Reset to 1 day
Daily Newsletter Sections:
Review These Today (spaced repetition items)
Test Yourself (active recall questions)
Connections You Might Have Missed (synthesis)
This Week's Focus (what needs attention)
Core Prompts:
Framework Prompt — Get the mental models first
Deep Dive Prompt — Socratic method on specifics
Newsletter Prompt — Daily review generation
Question Prompt — Log and connect new information
Expert Test Prompt — Verify readiness before high-stakes meetings
The Insight:
Reacting to a draft is easier than creating from scratch (previous guide)
Retrieval with spaced repetition beats cramming for durable expertise
TL;DR
The problem: Consultants need to become experts in new domains faster than traditional learning allows.
The insight: Spaced repetition + active recall + AI teaching = genuine expertise in weeks instead of years.
The system: Claude Code teaches you via Socratic dialogue, logs concepts to Notion, manages review schedules, and generates daily newsletters calibrated to your knowledge state.
The workflow:
Start a learning session focused on mental models
Go deep on specifics using Socratic method
Log every concept with review dates
Generate daily newsletter with recall questions
Review, answer, update confidence
Repeat until expertise is real
The compound effect: Knowledge connects across domains. The 10th field takes half the time of the first.
The key: Consistency beats intensity. Daily review is non-negotiable.
Start today: One domain. Thirty minutes. First newsletter tomorrow.
You don't have years. But with the right system, you don't need them.