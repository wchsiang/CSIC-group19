# Draft AI Usage Guidelines

## Section 1 — What AI tools we plan to use, and what we will use each for

- We will use Claude to brainstorm implementation approaches, generate boilerplate code, and create first-draft unit tests. We will not use it to make final architectural decisions or to write security-critical code such as authentication and authorization logic without human review.

- We will use AI tools to generate an initial draft of documentation, comments, and test cases. A human team member must verify the accuracy and completeness of the generated content before it is added to the repository.

- AI may be used to compare possible technical approaches, but the final decision must be made by the team based on project requirements, technical evidence, and discussion. AI output alone will not determine our implementation.

## Section 2 — How we will document AI interactions

- Any AI interaction that produces code, documentation, or a technical decision that is eventually used in the repository must be recorded in the prompt engineering log. The record should include the prompt, the AI tool/model used, and a brief description of what was kept, modified, or rejected.

- One-off questions, such as simple syntax checks, error-message explanations, or general programming questions that do not directly contribute to the final repository, do not require a prompt log entry.

- Every pull request that contains AI-assisted work will include a brief statement indicating whether and how AI was used. The PR description does not need to contain the full conversation; it should point to the relevant prompt log when necessary.

- If an AI suggestion causes us to change our original technical approach or make an important design decision, the reasoning must also be recorded in `DECISIONS.md`. The decision record should explain the problem, the alternatives considered, and why the team chose the final approach.

- The prompt log records AI interactions, while `DECISIONS.md` records important decisions and their reasoning. These two records should not be treated as interchangeable.

## Section 3 — How we will handle disagreements about AI output quality

- If team members disagree about whether AI-generated code is suitable for merging, the code reviewer assigned to the pull request has the final say. The decision should be based on evidence rather than on who generated the code or who has more experience.

- Before AI-assisted code can be merged, it must pass the existing test suite, satisfy the project's linting and style requirements, and pass human code review.

- At least one team member other than the person who generated the AI-assisted code must be able to explain what the code does and why it is correct before it is merged.

- A team vote by itself is not considered sufficient evidence that AI-generated code is correct. If the disagreement cannot be resolved through tests, documentation, project conventions, or code review, the assigned code reviewer makes the final decision and records the reasoning in `DECISIONS.md` when the issue is significant.