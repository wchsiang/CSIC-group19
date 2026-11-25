# Draft AI Usage Guidelines

## Section 1 — What AI tools we plan to use, and what we will use each for

- Team members may use any LLM or AI coding assistant (e.g., Claude Code, Gemini, Cursor) for brainstorming, boilerplate code, and draft unit tests, provided the exact tool and model name are explicitly declared under `## AI assistance` (`Tool and model:`) in the PR description. If AI generates or modifies security-critical or core architectural logic (such as authentication, authorization, or database concurrency/locking), the PR author must document the specific human edits in `What I changed afterwards, and why` and pass line-by-line review from at least one teammate before merging.

- We will use AI tools to generate an initial draft of documentation, comments, and test cases. A human team member must verify the accuracy and completeness of the generated content before it is added to the repository.

- AI may be used to compare possible technical approaches, but the final decision must be made by the team based on project requirements, technical evidence, and discussion. AI output alone will not determine our implementation.

## Section 2 — How we will document AI interactions

- Any AI interaction that produces code, documentation, or a technical decision that is eventually used in the repository must be recorded in the prompt engineering log. The record should include the prompt, the AI tool/model used, and a brief description of what was kept, modified, or rejected.

- One-off questions, such as simple syntax checks, error-message explanations, or general programming questions that do not directly contribute to the final repository, do not require a prompt log entry.

- Every pull request must complete the `## AI assistance` section of the PR template. If AI was used, the author must fill in all four fields—(1) tool and model, (2) specific files or functions generated, (3) a one-line summary of the instruction (or link to the full prompt/spec if long), and (4) what the author changed afterwards and why—rather than leaving a generic statement.

- If an AI suggestion causes us to change our original technical approach or make an important design decision, the reasoning must also be recorded in `DECISIONS.md`. The decision record should explain the problem, the alternatives considered, and why the team chose the final approach.

- The prompt log records AI interactions, while `DECISIONS.md` records important decisions and their reasoning. These two records should not be treated as interchangeable.

## Section 3 — How we will handle disagreements about AI output quality

- If team members disagree about whether AI-generated code is suitable for merging, the code reviewer assigned to the pull request has the final say. The decision should be based on evidence rather than on who generated the code or who has more experience.

- Before AI-assisted code can be merged, it must pass the existing test suite, satisfy the project's linting and style requirements, and pass human code review.

- Before a PR is approved, the author must check off `I read every line of this change myself and can explain it without the AI` and provide concrete verification in `## How I checked it` (local/CI test status, manual checks/screenshots, or before/after prompt test suite results if prompts changed). Additionally, at least one reviewer must verify that the author's `What I changed afterwards, and why` and `Risks and alternatives` entries accurately match the actual diff before approving.

- A team vote by itself is not considered sufficient evidence that AI-generated code is correct. If the disagreement cannot be resolved through tests, documentation, project conventions, or code review, the assigned code reviewer makes the final decision and records the reasoning in `DECISIONS.md` when the issue is significant.