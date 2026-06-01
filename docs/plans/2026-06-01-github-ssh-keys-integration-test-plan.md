# GitHub SSH Keys Integration Test Plan

Date: 2026-06-01
Owner: Luna Supervisor
Status: Draft

## Goal

Validate the new GitHub SSH key integration end to end: users can provide a GitHub SSH key, the worker can use it for the intended repo operation, key material is handled safely, and failures are clear when credentials are missing, invalid, or over-scoped.

## Scope

In scope:

- GitHub SSH key registration/configuration flow.
- Private repo clone/pull using SSH.
- Public repo clone behavior with and without SSH credentials.
- Read-only deploy key behavior.
- Write-capable key behavior when explicitly required.
- Noninteractive worker behavior, including fail-fast errors.
- Key handling controls: storage, file permissions, cleanup, logging redaction, and host key verification.

Out of scope:

- GitHub OAuth or HTTPS token flows.
- Non-GitHub SSH hosts.
- Long-lived interactive SSH prompts.
- Production rollout metrics beyond the validation checks listed here.

## Assumptions

- The preferred credential type is a dedicated repo-scoped deploy key.
- Read-only keys are the default for clone/analyze workflows.
- Write-capable keys are allowed only when the worker must push branches or tags.
- The worker runs noninteractively, so passphrase-protected SSH keys should fail unless a safe noninteractive unlock flow exists.
- Key material must never appear in logs, trace output, shell history, error messages, or persisted artifacts.

## Success Criteria

- A private GitHub repo can be cloned using a valid read-only SSH deploy key.
- Public repos still clone successfully without configured GitHub credentials.
- Known private repo operations fail fast when no usable credentials are configured.
- Invalid, malformed, encrypted, revoked, or mismatched keys produce typed, actionable errors.
- Key files are created with `0600` permissions and removed after the turn/job.
- SSH uses `IdentitiesOnly`, `BatchMode`, strict host key checking, and pinned `github.com` host keys.
- No secret material is logged or exposed in user-facing output.
- Write access requires an explicit advanced selection and is auditable.

## Test Matrix

| Case | Credential | Repo Type | Operation | Expected Result |
| --- | --- | --- | --- | --- |
| 1 | None | Public | Clone | Succeeds unauthenticated |
| 2 | None | Private | Clone | Fails fast with missing credentials error |
| 3 | Valid read-only deploy key | Private allowed repo | Clone | Succeeds |
| 4 | Valid read-only deploy key | Private allowed repo | Pull | Succeeds |
| 5 | Valid read-only deploy key | Private allowed repo | Push branch | Fails with read-only permission error |
| 6 | Valid write-capable key | Private allowed repo | Push branch | Succeeds only when write mode is explicitly enabled |
| 7 | Valid key for different repo | Private repo | Clone | Fails with repo access error |
| 8 | Malformed key | Private repo | Clone | Fails validation before SSH attempt |
| 9 | Passphrase-protected key | Private repo | Clone | Fails with unsupported encrypted key error unless unlock flow exists |
| 10 | Revoked/deleted key | Private repo | Clone | Fails with authentication error |
| 11 | Broad personal key | Private repo | Configure | Allowed only with warning and audit metadata |
| 12 | Host key mismatch | Any SSH repo | Clone | Fails closed; does not learn host key dynamically |

## Validation Steps

1. Prepare fixtures:
   - One public GitHub repo.
   - One private GitHub repo with a read-only deploy key.
   - One private GitHub repo with a write-capable key for a controlled test branch.
   - One private GitHub repo that the test key cannot access.

2. Validate credential preflight:
   - Run a private repo clone with no key configured.
   - Confirm the worker returns a typed missing-credential error before attempting a long-running clone.
   - Confirm public clone still works without credentials.

3. Validate read-only happy path:
   - Configure a repo-scoped read-only deploy key.
   - Clone the private repo over SSH.
   - Pull the latest commit.
   - Attempt a push to a throwaway branch and confirm it is rejected.

4. Validate write-capable path:
   - Enable the explicit write-capable option.
   - Configure the write-capable test key.
   - Push a throwaway branch or tag.
   - Delete the throwaway branch or tag after validation.
   - Confirm audit metadata records that write access was selected.

5. Validate negative credential cases:
   - Submit malformed key material.
   - Submit a passphrase-protected key.
   - Submit a revoked key.
   - Submit a key scoped to a different repo.
   - Confirm each case returns a specific error and does not fall back to prompts.

6. Validate security controls:
   - Inspect worker logs for key material, key paths, SSH command output, and environment dumps.
   - Confirm temporary key files are `0600`.
   - Confirm temporary key files are removed after the turn/job.
   - Confirm `BatchMode=yes`, `IdentitiesOnly=yes`, strict host key checking, and pinned GitHub host keys are used.

## Demo Script

1. Show public repo clone with no GitHub SSH key configured.
2. Show private repo preflight failure with no key configured.
3. Add a read-only deploy key and clone the private repo successfully.
4. Attempt a push with the read-only key and show the expected permission failure.
5. Switch to explicit write-capable mode and push a throwaway branch.
6. Show cleanup evidence: no key material in logs and no leftover key file.

## Required Error Messages

- Missing credentials: "No valid GitHub SSH credentials are configured for this worker. Add a repo-scoped deploy key, then retry."
- Malformed key: "The provided SSH key is not a valid private key."
- Encrypted key: "Passphrase-protected SSH keys are not supported in this noninteractive worker."
- Access denied: "The configured SSH key does not have access to this repository."
- Write denied: "The configured SSH key is read-only. Enable an explicit write-capable credential only if this worker must push branches or tags."
- Host key failure: "GitHub host key verification failed. The operation was stopped before credentials were used."

## Rollout Checks

- Feature flag enabled for internal tenant only.
- Audit event emitted for credential creation, credential use, failed auth, and write-capable selection.
- Documentation recommends read-only deploy keys as the primary path.
- UI warning appears for broad or personal keys.
- Regression test covers public unauthenticated clone.

## Open Questions

- Do we already have a safe passphrase unlock design, or should encrypted keys remain unsupported?
- Where should audit metadata be surfaced for support review?
- Should write-capable keys require a second confirmation per repo or per operation?
