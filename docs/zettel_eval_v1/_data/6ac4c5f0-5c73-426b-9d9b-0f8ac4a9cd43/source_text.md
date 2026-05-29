## Core Concept: Solving the 'Presence Problem'
- Paperboy is an AI designed to be an always-on personal presence.
- Understands a user by observing their screen, conversations, and decisions.
- Aims to solve the 'presence problem'—the gap between cognitive capacity and life's demands.
- Proactively notices and handles issues, rather than just being a better data storage tool.

## System Architecture: Neural Network Analogy
- Architecture modeled on neural networks: AI agents are like neurons, intelligence emerges from connections.
- The 'knowledge graph' acts as the weight matrix, accumulating a model of the user.
- User corrections function as backpropagation, adjusting specific weights.
- An attention mechanism dynamically loads relevant knowledge for each query.
- Memory gates (input, forget, output) manage what is learned and surfaced.
- Incorporates concepts like dropout for anti-fragility and a mixture-of-experts model.

### Agent Organization
- Agents are organized by 'surfaces' (where they operate, e.g., Slack, code, email) rather than capabilities.
- Each surface agent maintains private memory.
- A central 'gardener' agent cross-pollinates insights to create a unified user model.

## Five Speeds of Operation
- Each surface operates at five distinct speeds, extending to physical presence in meetings.

### Reflex (Sub-second)
- Local, sub-second actions like autocomplete that reshape the interface.

### Glance (1-2 seconds)
- Contextual information like tooltips or suggestion chips.

### Think (Seconds-to-a-minute)
- Conversational responses like drafting replies or diagnosing problems.

### Work (Deep dives)
- Produces interactive, generated UI (called 'canvases') like reports or refactored code.

### Background (Continuous)
- Continuous, unnoticed tasks like finding flaky tests or nudging on deadlines.

### Physical Presence Extension
- Interpreting audio, surfacing context, decoding subtext, and handling follow-ups in meetings.

## Explicit Loss Function for Personal AI
- Addresses silent omissions, which are identified as the biggest failures of personal AI.
- Uses an explicit loss function with five signals:
- Accuracy: Correctness of information or actions.
- Latency: Speed of response or action.
- Autonomy: Degree of independent action.
- Taste: The difference between a draft and the user's final version.
- Absence: What the system should have noticed but didn't.

## Lessons from Multi-Agent Systems and Remaining Challenges
- Lessons from multi-agent systems, validated by Cursor at a 1,000-agent scale, include:
- Peer coordination fails.
- Single agents with too many roles break.
- Optimizing for convergence beats requiring perfect correctness at each step.
- Hard problems remain, including irreversibility of actions, user contradictions, and respecting the user's 'identity line'.

## Privacy as Architecture and Business Model
- Building a future where the human is at the center, making the user the loss function.
- Employs 'privacy as architecture':
- Data is encrypted on the user's machine by default.
- No aggregate data collection.
- No general model training on user data.
- The business model is reliant on earning user trust for delegation.
- The system's competitive moat is the irreducible time it spends learning a user's judgment, voice, and values.