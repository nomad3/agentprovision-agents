/*
 * @deprecated — use TerminalPanel directly. This re-export preserves
 * any import sites in tests or external consumers. Remove after one
 * release cycle.
 *
 * Phase B of the VSCode-style terminal redesign split the monolithic
 * TerminalCard into TerminalPanel (chrome + multi-group layout) and
 * TerminalGroup (single tab strip + <pre> stream). See
 * docs/plans/2026-05-16-terminal-vscode-style-redesign.md.
 */
export { default } from './TerminalPanel';
