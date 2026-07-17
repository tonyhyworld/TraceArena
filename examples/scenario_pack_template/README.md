# Scenario pack template

Copy this directory to start a new TraceArena world. Replace every
`TODO` value, add a deterministic fixture, and keep domain-specific rules in
the pack rather than in `backend/app/engine`.

Required questions:

1. What shared world do agents enter?
2. What can each agent observe and do?
3. What constraints can reject an action?
4. What changes after an accepted action?
5. Which authority settles the result, and what evidence does it cite?

Use the [scenario-pack guide](../../docs/scenario-pack-guide.md) for the full
contract. A contribution is not complete until another developer can replay it
from a clean checkout and explain the result from the recorded trace.
