# Personal Brave application autofill

1. Keep Job Hunting open. In your normal Brave, open `brave://extensions`, enable Developer mode, click **Load unpacked**, and select this folder.
2. In the desktop app, choose Settings / **VINCULAR EXTENSIÓN DE RELLENADO**. Copy its local pairing code, open this extension and click **VINCULAR** after pasting the code.
3. Select an application and click **RELLENAR AUTOMÁTICAMENTE EN MI BRAVE**. The normal browser opens; the extension wakes through the paired loopback bridge. The popup does not need to stay open. Pairing persists locally.
4. On an extension update, reload it with the circular arrow in `brave://extensions`; do not reinstall or republish a pairing code.

The scanner recognizes labels, placeholders and individual field containers. It can follow a checked Apply link, recover matching job forms in new/existing tabs and inspect accessible embedded documents. Company/role and task scope are checked before adopting an unlisted destination. It preserves manual input, leaves unknown answers blank, and reports missing steps through the desktop notice and an in-page message.

Only the selected person's confirmed information and reviewed role-matched CV are used. Autofill/upload can transmit applicant information to the selected employer before final submission. Authentication, CAPTCHA, terms, sensitive documents and unsupported controls are manual. The extension does not click Submit, create accounts or solve CAPTCHA.

The bridge binds to 127.0.0.1:18746 and uses a local secret. Never commit/share the generated `data/extension-pair.json`. No cookies, browser profile, passwords or applicant records are bundled. The browser tab is not closed when preparation ends. Observation expires after 30 minutes or when the app/task is retired; select the application again if needed.

The optional local OCR monitor re-inspects the linked application in the focused Brave window, using Windows OCR in a Qt worker thread. It does not store screenshots. Form support varies by portal, frame access and control design; unsupported steps remain available for manual completion.
