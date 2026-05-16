# INTEMO Extension Packages

Packaged extension ZIPs are provided for Chrome, Edge, Brave, Opera, Firefox, Safari-compatible source, Gmail-only Chrome use, and the Outlook add-in.

## Install for Chromium browsers
1. Open chrome://extensions, edge://extensions, brave://extensions, or opera://extensions.
2. Enable Developer mode.
3. Extract the matching ZIP and choose Load unpacked.
4. Select the extracted extension folder.

## Install for Firefox
1. Open about:debugging#/runtime/this-firefox.
2. Choose Load Temporary Add-on.
3. Select manifest.json from the extracted Firefox ZIP.

## Install for Outlook
1. Extract the Outlook add-in ZIP.
2. In Outlook, open add-ins and choose the custom add-in / sideload option.
3. Select manifest.xml from the extracted Outlook add-in folder.
4. Keep the local INTEMO service running at http://127.0.0.1:4597.

The extension only talks to the local service at http://127.0.0.1:4597 or http://localhost:4597. It does not store OAuth refresh tokens or mailbox passwords.
