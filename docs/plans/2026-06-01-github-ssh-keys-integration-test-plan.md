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
- Key handling controls: vault/KMS-backed storage, tenant-scoped retrieval, RBAC, file permissions, cleanup, logging redaction, ambient SSH isolation, and host key verification.

Out of scope:

- GitHub OAuth or HTTPS token flows.
- Non-GitHub SSH hosts.
- Long-lived interactive SSH prompts.
- Production rollout metrics beyond the validation checks listed here.

## Assumptions

- The preferred credential type is a dedicated repo-scoped deploy key.
- Read-only keys are the default for clone/analyze workflows.
- Write-capable keys are allowed only when the worker must push branches or tags.
- Credentials are scoped by tenant, integration, and repository; a key registered for one tenant or repo must not be usable by another.
- Private keys are stored only in an approved encrypted vault/KMS-backed store, never plaintext in the database, logs, artifacts, shell history, or backups.
- Credential creation, credential use, write-capable selection, and internal overrides require explicit RBAC authorization.
- The worker runs noninteractively, so passphrase-protected SSH keys should fail unless a safe noninteractive unlock flow exists.
- The worker may inherit ambient SSH config or agent state; the GitHub SSH path must ignore it and use only the intended temporary key and pinned known-hosts file.
- SSH host keys are pinned from trusted GitHub metadata and never learned dynamically during a worker turn.
- Key material must never appear in logs, trace output, shell history, error messages, or persisted artifacts.
- Temporary key paths are treated as sensitive because they can expose tenant and integration identifiers.
- Broad personal-key blocking must be enforceable through GitHub deploy-key metadata/identity verification or a trusted deploy-key creation flow; raw private key material alone is not enough to prove repo scope.

## Success Criteria

- A private GitHub repo can be cloned using a valid read-only SSH deploy key.
- Public repos still clone successfully without configured GitHub credentials.
- Public repos also clone without materializing or offering tenant SSH credentials when credentials exist but are not explicitly required.
- Known private repo operations fail fast when no usable credentials are configured.
- Invalid, malformed, encrypted, revoked, or mismatched keys produce typed, actionable errors.
- Stored private keys are encrypted at rest in an approved vault/KMS-backed store and are retrievable only through tenant-scoped, repo-scoped authorization.
- Key files are created with `0600` permissions and removed after the turn/job.
- SSH uses `GIT_SSH_COMMAND` with an explicit `-i` key path, `-F /dev/null`, `IdentitiesOnly=yes`, `BatchMode=yes`, `LogLevel=ERROR`, strict host key checking, and pinned `github.com` host keys.
- The worker neutralizes ambient SSH and Git configuration that could change identity or tracing behavior, including `SSH_AUTH_SOCK`, `GIT_SSH`, `GIT_TRACE*`, and inherited `HOME`/`.ssh` config.
- No secret material, temporary key path, credential fingerprint, or raw SSH command is logged or exposed in user-facing output.
- Unauthorized users cannot create credentials, trigger credential-backed operations, select write-capable mode, or approve internal personal-key overrides.
- Write access requires an explicit advanced selection and is auditable per tenant, repo, operation, and initiating user/session.
- Broad personal keys are blocked by default; any temporary internal override must require tenant/admin policy approval, explicit advanced override, a recorded reason, warning text, and audit metadata.

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
| 11 | Broad personal key | Private repo | Configure | Blocked by default; internal override requires tenant/admin policy approval, advanced override, reason, warning, and audit metadata |
| 12 | Host key mismatch | Any SSH repo | Clone | Fails closed; does not learn host key dynamically |
| 13 | Valid key from different tenant | Private allowed repo | Clone | Fails tenant isolation preflight before SSH attempt |
| 14 | Valid key from different tenant for same repo URL/name | Private allowed repo | Clone | Fails tenant isolation preflight; key is not selectable, inferred, logged, or used |
| 15 | Valid credential configured | Public repo | Clone | Succeeds without writing a temp key or offering tenant SSH identity unless explicitly required |
| 16 | Low-privilege user | Private allowed repo | Configure/use/write override | Denied by RBAC with no credential retrieval |
| 17 | Ambient SSH config/agent present | Private allowed repo | Clone | Uses only explicit temp key and pinned known-hosts; ignores ambient config, agent, and tracing env |
| 18 | Unverifiable broad/account key | Private repo | Configure | Rejected unless deploy-key metadata/identity verification proves repo scope or trusted creation flow is used |

## Validation Steps

1. Prepare fixtures:
   - One public GitHub repo.
   - One private GitHub repo with a read-only deploy key.
   - One private GitHub repo with a write-capable key for a controlled test branch.
   - One private GitHub repo that the test key cannot access.
   - One low-privilege tenant user and one admin/authorized user for RBAC checks.
   - A worker environment with ambient `~/.ssh/config`, `SSH_AUTH_SOCK`, `GIT_SSH`, and `GIT_TRACE*` values set to prove the GitHub SSH path ignores them.

2. Validate credential preflight:
   - Run a private repo clone with no key configured.
   - Confirm the worker returns a typed missing-credential error before attempting a long-running clone.
   - Confirm public clone still works without credentials.
   - Confirm public clone still avoids writing a temporary SSH key or offering tenant SSH identity when credentials exist but are not explicitly required.
   - Confirm a key registered under another tenant, integration, or repo is rejected before writing a temporary key file.
   - Confirm tenant A credentials cannot be selected, inferred, logged, or used by tenant B, including same repo URL/name edge cases.

3. Validate storage, authorization, and credential selection:
   - Confirm credential creation and use are denied for users without the required tenant/integration/repo permission.
   - Confirm write-capable selection and any internal personal-key override require admin/tenant policy approval and a recorded reason.
   - Confirm stored private keys are encrypted through the approved vault/KMS-backed store and never persisted plaintext in the database, logs, artifacts, shell history, or backups.
   - Confirm worker retrieval requires tenant-scoped and repo-scoped authorization before any temporary key file is written.
   - Confirm broad or personal key rejection is backed by GitHub deploy-key metadata/identity verification or by using a trusted deploy-key creation flow.

4. Validate read-only happy path:
   - Configure a repo-scoped read-only deploy key.
   - Clone the private repo over SSH.
   - Pull the latest commit.
   - Attempt a push to a throwaway branch and confirm it is rejected.

5. Validate write-capable path:
   - Enable the explicit write-capable option.
   - Configure the write-capable test key.
   - Push a throwaway branch or tag.
   - Delete the throwaway branch or tag after validation.
   - Confirm audit metadata records that write access was selected, which repo was targeted, and which session initiated it.

6. Validate negative credential cases:
   - Submit malformed key material.
   - Submit a passphrase-protected key.
   - Submit a revoked key.
   - Submit a key scoped to a different repo.
   - Confirm each case returns a specific error and does not fall back to prompts.

7. Validate security controls:
   - Inspect worker logs for key material, key paths, SSH key fingerprints, raw constructed SSH commands, SSH command output, and environment dumps.
   - Confirm temporary key files are `0600`.
   - Confirm temporary key files are removed after the turn/job.
   - Confirm no temporary key file remains after success, failure, worker cancellation, or timeout.
   - Confirm `GIT_SSH_COMMAND` includes an explicit `-i` key path, `-F /dev/null`, `BatchMode=yes`, `IdentitiesOnly=yes`, strict host key checking, a pinned `UserKnownHostsFile`, and `LogLevel=ERROR`.
   - Confirm the worker unsets or neutralizes `SSH_AUTH_SOCK`, `GIT_SSH`, `GIT_TRACE*`, and inherited `HOME`/`.ssh` config before invoking GitHub SSH.
   - Confirm a changed or missing pinned `github.com` host key fails closed before credentials are offered.

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
- Unauthorized credential use: "You are not authorized to configure or use GitHub SSH credentials for this tenant, integration, or repository."
- Write denied: "The configured SSH key is read-only. Enable an explicit write-capable credential only if this worker must push branches or tags."
- Host key failure: "GitHub host key verification failed. The operation was stopped before credentials were used."

## Rollout Checks

- Feature flag enabled for internal tenant only.
- Audit event emitted for credential creation, credential use, failed auth, and write-capable selection.
- RBAC enforced for credential creation, credential use, write-capable selection, and internal personal-key override approval.
- Credential storage verified against the approved vault/KMS-backed store with no plaintext persistence in database, logs, artifacts, shell history, or backups.
- Registration either creates/verifies repo-scoped deploy keys through GitHub metadata or rejects unverifiable raw personal/account keys.
- Documentation recommends read-only deploy keys as the primary path.
- Broad or personal keys are denied by default; any internal override requires tenant/admin policy approval, explicit advanced selection, a recorded reason, UI warning text, and audit metadata.
- Regression test covers public unauthenticated clone and public clone with unrelated credentials configured but unused.

## Open Questions

- Do we already have a safe passphrase unlock design, or should encrypted keys remain unsupported?
- Where should audit metadata be surfaced for support review?
- Should write-capable keys require a second confirmation per repo or per operation?
