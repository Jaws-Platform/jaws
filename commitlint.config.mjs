import onlyCoauthorTrailers from "./tools/commitlint/only-coauthor-trailers.mjs";
import singleScope from "./tools/commitlint/single-scope.mjs";
import subjectLowercase from "./tools/commitlint/subject-lowercase.mjs";

// The commit types. One closed set, identical in every repository: copy it
// unchanged and never add to it.
export const TYPES = [
  "feat",
  "fix",
  "perf",
  "revert",
  "docs",
  "refactor",
  "test",
  "build",
  "ci",
  "style",
  "chore",
];

// This repository's scopes: the only ones a commit may use. Every repository
// defines its own set. `deps` and `release` are in every set because
// Dependabot and Release Please write them. The Scopes table in
// CONTRIBUTING.md mirrors this object, in the same order; `npm test` fails if
// the two drift apart.
export const SCOPES = {
  cli: "The jaws CLI in src/jaws/, its tests and its Docker image",
  config: "config/: the accounts, the project registry and the central guardrails",
  foundation: "The foundation stack in foundation/",
  sites: "The site stack and the site workflows",
  bots: "The bot stack, bot and research projects, and remote tasks",
  databricks: "The Databricks account and workspace stacks",
  access: "owner-access/ and data-access/",
  monitoring: "The monitoring/ and billing-export/ roots, config/monitoring.yaml and their docs",
  publishing: "release-infra/: Jaws's ECR Public repository and the role that publishes the image to it",
  datasets: "datasets/, the onboarded datasets",
  workflows: "The reusable workflows and composite actions in .github/",
  repo: "README, CONTRIBUTING, AGENTS, commitlint, the PR and issue templates, and repository tooling",
  deps: "Dependency updates, mostly Dependabot's",
  release: "Release Please's release pull requests and its config",
};

// A commit message is exactly one line, `type(scope): subject`, of at most
// 100 characters. The only thing allowed after it is a blank line followed by
// `Co-authored-by: Name <email>` trailers. Detail belongs in the pull request.
export default {
  extends: ["@commitlint/config-conventional"],
  plugins: [
    {
      rules: {
        "only-coauthor-trailers": onlyCoauthorTrailers,
        "single-scope": singleScope,
        "subject-lowercase": subjectLowercase,
      },
    },
  ],
  // Do not silently skip merge, fixup or revert messages: history is linear
  // and every commit on main is a Conventional Commit.
  defaultIgnores: false,
  rules: {
    "header-max-length": [2, "always", 100],
    "type-enum": [2, "always", TYPES],
    "scope-enum": [2, "always", Object.keys(SCOPES)],
    "scope-empty": [2, "never"],
    "single-scope": [2, "always"],
    // Lowercase subjects, except Dependabot's fixed `chore(deps): Bump ...`.
    "subject-case": [0],
    "subject-lowercase": [2, "always"],
    "only-coauthor-trailers": [2, "always"],
    // The local rule above is the authority on everything after the header;
    // the built-in body and footer rules would only produce duplicates.
    "body-max-line-length": [0],
    "footer-max-line-length": [0],
    "body-leading-blank": [0],
    "footer-leading-blank": [0],
  },
};
