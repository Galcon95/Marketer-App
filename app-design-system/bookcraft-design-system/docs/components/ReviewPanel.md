Human-in-the-loop review drawer: the agent's drafted pitch beside the auditor's verification report, with Approve & Dispatch, Reject with Feedback and Edit Copy.

**Props:** `draft` (text), `checks` `[{ok, label, detail?}]`, `score`, `target` (where it will be posted), `title`, `onApprove`, `onReject`, `onEdit`.

- Approve & Dispatch is the only `success` button in the product. Reject first opens a feedback textarea, then sends it back to the Copywriter.
- Edit Copy makes the draft editable in place with an `accent-text` outline.
- Failed checks use the `alert` icon in `warning-text` and never block Approve — the human decides.
