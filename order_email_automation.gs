/**
 * Foodland Wudinna — Weekly Order Email → GitHub Automation
 * ============================================================
 * Polls Gmail every 5 minutes (via a time-driven trigger) for two weekly
 * attachments and commits them to the foodland_wudinna GitHub repo so the
 * GitHub Actions workflow can generate the order sheet unattended.
 *
 * SENDERS WATCHED
 *   Specials bulletin  : admin@wudinnafoodland.com.au        → specials_YYYY-MM-DD.<ext>
 *   Stock-on-hand      : postmaster@mg.gapsolutions.com.au   → stock_on_hand_YYYY-MM-DD.xlsx
 *
 * DATE LOGIC
 *   SPECIALS: The cycle date is extracted directly from the bulletin document.
 *     Every bulletin contains a header line "Week Commencing: DD.MM.YYYY".
 *     That date is used as-is for the filename, regardless of which day the
 *     email arrived. This is reliable because the bulletin is always for the
 *     Wednesday that starts the specials cycle — even when it arrives Thursday
 *     or Friday. Falls back to getUpcomingWednesday() if the pattern is missing.
 *
 *   SOH: The filename date is the upcoming Wednesday (today if today is
 *     Wednesday, otherwise next Wednesday). The SOH report has no explicit
 *     cycle date in the document, so arrival-day logic is the correct approach.
 *
 * SPECIALS FILE EXTENSION
 *   The target name uses the real attachment extension (.doc or .docx),
 *   not a hard-coded ".doc". generate_order_headless.py already handles both.
 *
 * SCRIPT PROPERTIES (set via Extensions → Apps Script → Project Settings)
 *   GITHUB_TOKEN   — Fine-grained PAT, Contents: read + write, scoped to this repo
 *   GITHUB_OWNER   — GitHub username or org  (e.g. "fabio-tavares")
 *   GITHUB_REPO    — Repository name          (e.g. "foodland_wudinna")
 *   GITHUB_BRANCH  — Branch to commit to      (default: "main")
 */

// ---------------------------------------------------------------------------
// Configuration constants — only change if sender addresses change
// ---------------------------------------------------------------------------
const SPECIALS_SENDER = 'admin@wudinnafoodland.com.au';
const SOH_SENDER      = 'postmaster@mg.gapsolutions.com.au';

/** Gmail label applied after a message is successfully processed.
 *  Acts as a processed-flag so the same email is never committed twice.
 *  Created automatically on first run if it doesn't exist. */
const PROCESSED_LABEL = 'OrderBot/Processed';

/** GitHub path prefix inside the repo where both files land. */
const GITHUB_TARGET_DIR = '03_model/inputs';


// ---------------------------------------------------------------------------
// Entry point — wired to the time-driven trigger (every 5 minutes)
// ---------------------------------------------------------------------------
function processOrderEmails() {
  const label = getOrCreateLabel(PROCESSED_LABEL);

  Logger.log('=== processOrderEmails start ===');

  let processed = 0;
  let errors    = 0;

  // --- Specials bulletin ---------------------------------------------------
  // Cycle date is read from the document ("Week Commencing: DD.MM.YYYY").
  // This means the file is named correctly even when the email arrives a day
  // or two after the cycle has started.
  // mimePrefer: the script tries these MIME types in order before falling back.
  // Images in the email (inline artwork, banners) are explicitly rejected.
  try {
    const ok = processAttachmentFromSender({
      sender:         SPECIALS_SENDER,
      buildFileName:  (ext, blob) => `specials_${extractCycleDateFromBlob(blob)}.${ext}`,
      // Match by filename extension, not MIME type — .doc files are often sent
      // as application/octet-stream (generic binary) by email clients, so MIME
      // matching is unreliable. Extension is the correct signal here.
      docExtensions: ['.doc', '.docx'],
      processedLabel: label,
    });
    if (ok) processed++;
  } catch (e) {
    Logger.log(`[ERROR] Specials: ${e.message}`);
    errors++;
  }

  // --- Stock-on-hand report ------------------------------------------------
  // Cycle date is computed from the arrival day (next Wednesday or today if
  // today is Wednesday). The SOH report has no usable date in its content.
  try {
    const cycleDate = getUpcomingWednesday();
    const ok = processAttachmentFromSender({
      sender:         SOH_SENDER,
      buildFileName:  (_ext, _blob) => `stock_on_hand_${cycleDate}.xlsx`,
      mimeFilter:     'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      processedLabel: label,
    });
    if (ok) processed++;
  } catch (e) {
    Logger.log(`[ERROR] Stock-on-hand: ${e.message}`);
    errors++;
  }

  Logger.log(`=== Done | processed: ${processed}, errors: ${errors} ===`);
}


// ---------------------------------------------------------------------------
// Core processor
// Finds the latest unread, un-labelled message from `sender`, extracts the
// right attachment, commits it to GitHub, then marks the thread done.
//
// @param {object} opts
//   sender         {string}        From: address to search for
//   buildFileName  {function}      Called with (ext, blob); returns target filename
//   docExtensions  {string[]|null} Match by filename extension (e.g. ['.doc','.docx']).
//                                  More reliable than MIME type for Word files, which
//                                  are often sent as application/octet-stream.
//   mimeFilter     {string|null}   Exact MIME match — used for SOH xlsx
//   processedLabel {GmailLabel}    Applied to thread after processing
// @returns {boolean} true if a file was committed, false if no matching email found
// ---------------------------------------------------------------------------
function processAttachmentFromSender({ sender, buildFileName, docExtensions, mimeFilter, processedLabel }) {
  // Search: unread, from this sender, not yet labelled as processed.
  const query   = `from:(${sender}) is:unread -label:${PROCESSED_LABEL}`;
  const threads = GmailApp.search(query, 0, 10); // cap at 10 as a safety rail

  if (threads.length === 0) {
    Logger.log(`[INFO] No unread messages from ${sender}`);
    return false;
  }

  // GmailApp.search returns threads sorted newest-first — take the first one.
  const thread  = threads[0];
  const message = thread.getMessages().pop(); // most recent message in thread

  const attachments = message.getAttachments();
  if (attachments.length === 0) {
    Logger.log(`[WARN] Email from ${sender} has no attachments — marking read and skipping`);
    markProcessed(thread, processedLabel);
    return false;
  }

  // Log all attachments for visibility in the execution log.
  attachments.forEach((a, i) =>
    Logger.log(`[INFO] Attachment ${i}: ${a.getName()} (${a.getContentType()})`)
  );

  let attachment = null;

  if (docExtensions && docExtensions.length > 0) {
    // Match by filename extension — tried in order, first match wins.
    // This is more reliable than MIME type for .doc files, which email clients
    // often send as application/octet-stream regardless of content.
    for (const ext of docExtensions) {
      const match = attachments.find(a => a.getName().toLowerCase().endsWith(ext));
      if (match) { attachment = match; break; }
    }
    if (!attachment) {
      Logger.log(`[ERROR] No attachment with extension ${JSON.stringify(docExtensions)} found in email from ${sender}. Attachments: ${attachments.map(a => a.getName()).join(', ')}`);
      Logger.log('[ERROR] Marking processed to avoid loop — check that the specials email contains a .doc or .docx attachment.');
      markProcessed(thread, processedLabel);
      return false;
    }
  } else if (mimeFilter) {
    // Exact MIME match (used for SOH xlsx).
    const match = attachments.find(a => a.getContentType() === mimeFilter);
    if (match) {
      attachment = match;
    } else {
      Logger.log(`[WARN] No attachment matching ${mimeFilter} — using first attachment`);
      attachment = attachments[0];
    }
  } else {
    attachment = attachments[0];
  }

  // Derive extension from the real attachment name.
  const originalName = attachment.getName();
  const ext          = originalName.includes('.')
    ? originalName.split('.').pop().toLowerCase()
    : 'bin';

  // Build the blob once — buildFileName may read it to extract a date.
  const blob       = attachment.copyBlob();
  const targetName = buildFileName(ext, blob);
  const githubPath = `${GITHUB_TARGET_DIR}/${targetName}`;

  Logger.log(`[INFO] "${originalName}" from ${sender} → committing as ${githubPath}`);

  commitToGitHub({
    path:    githubPath,
    blob:    blob,
    message: `auto: ${targetName} (${new Date().toISOString()})`,
  });

  markProcessed(thread, processedLabel);
  Logger.log(`[OK] ${targetName} committed and email marked processed`);
  return true;
}


// ---------------------------------------------------------------------------
// Specials date extraction
// Reads the bulletin attachment bytes as text and searches for the
// "Week Commencing: DD.MM.YYYY" header that every Freshlink bulletin contains.
// Returns a YYYY-MM-DD string.
//
// WHY NOT LLM: The bulletin format is fixed and machine-readable. A regex is
// faster, cheaper, and more reliable than an API call for structured data
// extraction from a known template.
//
// Falls back to getUpcomingWednesday() if the pattern is not found, so a
// format change in the bulletin won't break the pipeline — it just logs a
// warning and uses arrival-day logic instead.
// ---------------------------------------------------------------------------
function extractCycleDateFromBlob(blob) {
  let text = '';
  try {
    // The blob bytes decode to text that contains readable content even for
    // binary .doc files — the header fields are stored as plain ASCII/UTF-8.
    text = Utilities.newBlob(blob.getBytes()).getDataAsString('UTF-8');
  } catch (e) {
    Logger.log(`[WARN] Could not decode bulletin bytes: ${e.message}`);
  }

  // Match "Week Commencing: 13.05.2026" — also handles / and - as separators,
  // and single-digit day/month (e.g. "3.5.2026").
  const match = text.match(
    /week\s+commencing[:\s]+(\d{1,2})[.\/-](\d{1,2})[.\/-](\d{4})/i
  );

  if (match) {
    const dd   = match[1].padStart(2, '0');
    const mm   = match[2].padStart(2, '0');
    const yyyy = match[3];
    const iso  = `${yyyy}-${mm}-${dd}`;
    Logger.log(`[INFO] Cycle date extracted from bulletin: ${iso}`);
    return iso;
  }

  // Fallback: derive from today's date.
  Logger.log('[WARN] "Week Commencing" pattern not found in bulletin — falling back to arrival-day date logic');
  return getUpcomingWednesday();
}


// ---------------------------------------------------------------------------
// GitHub Contents API — create or update a file at `path`
//
// Uses PUT /repos/{owner}/{repo}/contents/{path}.
// If the file already exists, fetches its SHA first (required for updates).
//
// @param {object} opts
//   path    {string}  Repo-relative file path (e.g. "03_model/inputs/foo.xlsx")
//   blob    {Blob}    File bytes
//   message {string}  Commit message
// ---------------------------------------------------------------------------
function commitToGitHub({ path, blob, message }) {
  const props  = PropertiesService.getScriptProperties();
  const token  = props.getProperty('GITHUB_TOKEN');
  const owner  = props.getProperty('GITHUB_OWNER');
  const repo   = props.getProperty('GITHUB_REPO');
  const branch = props.getProperty('GITHUB_BRANCH') || 'main';

  if (!token || !owner || !repo) {
    throw new Error(
      'Script Properties missing. Set GITHUB_TOKEN, GITHUB_OWNER, and GITHUB_REPO ' +
      'under Extensions → Apps Script → Project Settings → Script Properties.'
    );
  }

  const apiBase = `https://api.github.com/repos/${owner}/${repo}/contents/${path}`;
  const headers = {
    'Authorization':        `Bearer ${token}`,
    'Accept':               'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    'Content-Type':         'application/json',
  };

  // --- Step 1: check whether the file already exists (need SHA for updates) ---
  let existingSha = null;
  const getResp = UrlFetchApp.fetch(`${apiBase}?ref=${branch}`, {
    method:             'get',
    headers:            headers,
    muteHttpExceptions: true,
  });

  if (getResp.getResponseCode() === 200) {
    existingSha = JSON.parse(getResp.getContentText()).sha;
    Logger.log(`[INFO] File exists (SHA ${existingSha}) — will overwrite`);
  } else if (getResp.getResponseCode() !== 404) {
    throw new Error(
      `GitHub GET check failed: HTTP ${getResp.getResponseCode()} — ${getResp.getContentText()}`
    );
  }

  // --- Step 2: PUT the file ---
  const payload = {
    message: message,
    content: Utilities.base64Encode(blob.getBytes()),
    branch:  branch,
  };
  if (existingSha) payload.sha = existingSha; // mandatory when updating an existing file

  const putResp = UrlFetchApp.fetch(apiBase, {
    method:             'put',
    headers:            headers,
    payload:            JSON.stringify(payload),
    muteHttpExceptions: true,
  });

  const code = putResp.getResponseCode();
  if (code !== 200 && code !== 201) {
    throw new Error(
      `GitHub PUT failed: HTTP ${code} — ${putResp.getContentText()}`
    );
  }

  Logger.log(`[OK] GitHub responded ${code} for ${path}`);
}


// ---------------------------------------------------------------------------
// Date logic — SOH filename
// Returns the ISO date string (YYYY-MM-DD) for the current ordering cycle's
// Wednesday.
//
// RULE: if today is Wednesday → return today.
//       otherwise             → return the coming Wednesday.
//
// Used only for SOH filenames. Specials use extractCycleDateFromBlob() instead.
// ---------------------------------------------------------------------------
function getUpcomingWednesday() {
  const now = new Date();
  const dow = now.getDay(); // 0=Sun 1=Mon 2=Tue 3=Wed 4=Thu 5=Fri 6=Sat

  // Days until next Wednesday: 0 if today is Wednesday, 1–6 otherwise.
  const daysUntilWed = (3 - dow + 7) % 7;

  const target = new Date(now);
  target.setDate(now.getDate() + daysUntilWed);

  const yyyy = target.getFullYear();
  const mm   = String(target.getMonth() + 1).padStart(2, '0');
  const dd   = String(target.getDate()).padStart(2, '0');

  return `${yyyy}-${mm}-${dd}`;
}


// ---------------------------------------------------------------------------
// Gmail helpers
// ---------------------------------------------------------------------------

/** Returns the label with `name`, creating it if it doesn't exist. */
function getOrCreateLabel(name) {
  return GmailApp.getUserLabelByName(name) || GmailApp.createLabel(name);
}

/** Marks a thread as read and applies the processed label. */
function markProcessed(thread, label) {
  thread.markRead();
  thread.addLabel(label);
}


// ---------------------------------------------------------------------------
// Manual test helpers — run these from the Apps Script editor to verify setup
// ---------------------------------------------------------------------------

/**
 * Dry-run the date extraction against the latest unread specials email.
 * Does NOT commit anything or mark the email as read.
 * Check the execution log for the extracted cycle date.
 */
function testSpecialsDateExtraction() {
  const query   = `from:(${SPECIALS_SENDER}) is:unread -label:${PROCESSED_LABEL}`;
  const threads = GmailApp.search(query, 0, 1);

  if (threads.length === 0) {
    Logger.log('[INFO] No unread specials email found to test against');
    return;
  }

  const message     = threads[0].getMessages().pop();
  const attachments = message.getAttachments();

  if (attachments.length === 0) {
    Logger.log('[WARN] Email has no attachments');
    return;
  }

  const blob      = attachments[0].copyBlob();
  const extracted = extractCycleDateFromBlob(blob);
  const fallback  = getUpcomingWednesday();

  Logger.log(`Attachment: ${attachments[0].getName()}`);
  Logger.log(`Extracted cycle date : ${extracted}`);
  Logger.log(`Arrival-day fallback : ${fallback}`);
  Logger.log(extracted !== fallback
    ? '✓ Extraction succeeded — these differ, which is expected when email arrives Thu/Fri'
    : '— Dates match (email arrived on Wednesday, or extraction fell back to arrival-day logic)'
  );
}

/** Quick sanity check: prints the SOH cycle date that would be used right now. */
function testDateLogic() {
  Logger.log(`SOH cycle date would be: ${getUpcomingWednesday()}`);
}

/** Quick sanity check: verifies GitHub credentials are set and reachable.
 *  Does NOT write anything — just reads the target directory listing. */
function testGitHubConnection() {
  const props  = PropertiesService.getScriptProperties();
  const token  = props.getProperty('GITHUB_TOKEN');
  const owner  = props.getProperty('GITHUB_OWNER');
  const repo   = props.getProperty('GITHUB_REPO');
  const branch = props.getProperty('GITHUB_BRANCH') || 'main';

  const url = `https://api.github.com/repos/${owner}/${repo}/contents/${GITHUB_TARGET_DIR}?ref=${branch}`;
  const resp = UrlFetchApp.fetch(url, {
    method:             'get',
    headers: {
      'Authorization':        `Bearer ${token}`,
      'Accept':               'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    },
    muteHttpExceptions: true,
  });

  Logger.log(`GitHub connection test: HTTP ${resp.getResponseCode()}`);
  if (resp.getResponseCode() === 200) {
    const files = JSON.parse(resp.getContentText()).map(f => f.name);
    Logger.log(`Files in ${GITHUB_TARGET_DIR}: ${files.join(', ')}`);
  } else {
    Logger.log(`Response body: ${resp.getContentText()}`);
  }
}
