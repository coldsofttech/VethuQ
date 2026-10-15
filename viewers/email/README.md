# @vethuq/email-viewer

A read-only reader for an email message (`.eml` or Outlook `.msg`), for VethuQ's email preview. Like
the other viewers it lives outside `web/`, knows nothing about VethuQ or its API, and has no
dependency but React (a peer).

```jsx
<EmailViewer
  message={{
    head: [{ kind: 'from', text: 'From: Ada <ada@x.org>', start: 0 }, ...],  // the header lines
    body: [{ text: 'Prices fell', start: 38 }, ...],                          // the body, a line each
    attachments: [{ name: 'report.pdf', type: 'application/pdf', size: 2048 }],
  }}
  match={{ start: 45, end: 49 }}      // offsets in the indexed text: finds and marks the words
  onLocated={(place) => ...}          // 'headers', 'body' or null
/>
```

- A header line's `kind` is `from`, `to`, `cc`, `bcc`, `reply_to`, `subject`, `date` or `message_id`;
  its `text` keeps the label the index keeps (`From: `), which the viewer lays out itself.
- A line's `start` is where it begins in the text the message was indexed as (the header lines joined
  by a newline, a blank line, the body).
- The body is shown as text (an HTML body as the text it was indexed as), never rendered, so a
  message cannot load anything.
- Colours follow the Fluent UI theme variables when the page has them.
