const SPREADSHEET_ID = '1lxL3hA8NR_rt8mTG848BXXjplBHj98OtIrWhe9lKLIg';
const SHEET_NAME = 'backup';
const HEADERS = [
  'record_type',
  'page',
  'line_id',
  'line_number',
  'status',
  'anchor_y',
  'category',
  'note',
  'reviewed_fingerprint',
  'block_action',
  'block_start_line',
  'block_end_line',
  'page_signed_off',
  'page_signed_off_at',
  'reviewer_name',
  'updated_at',
];

function doGet() {
  try {
    return jsonResponse_({
      ok: true,
      ...loadReviewState_(),
    });
  } catch (error) {
    return jsonResponse_({
      ok: false,
      error: String(error),
    });
  }
}

function doPost(e) {
  try {
    const payload = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    const action = payload.action || 'savePage';

    if (action === 'savePage') {
      savePageReview_(payload);
      return jsonResponse_({
        ok: true,
        savedAt: new Date().toISOString(),
      });
    }

    if (action === 'saveAll') {
      saveAllReviews_(payload);
      return jsonResponse_({
        ok: true,
        savedAt: new Date().toISOString(),
      });
    }

    return jsonResponse_({
      ok: false,
      error: 'Unknown action: ' + action,
    });
  } catch (error) {
    return jsonResponse_({
      ok: false,
      error: String(error),
    });
  }
}

function openSheet_() {
  const spreadsheet = SpreadsheetApp.openById(SPREADSHEET_ID);
  let sheet = spreadsheet.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = spreadsheet.insertSheet(SHEET_NAME);
  }
  ensureHeaders_(sheet);
  return sheet;
}

function ensureHeaders_(sheet) {
  const headerRange = sheet.getRange(1, 1, 1, HEADERS.length);
  const current = headerRange.getValues()[0];
  const matches = HEADERS.every(function (header, index) {
    return current[index] === header;
  });
  if (!matches) {
    headerRange.setValues([HEADERS]);
  }
}

function getRows_(sheet) {
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) {
    return [];
  }
  return sheet.getRange(2, 1, lastRow - 1, HEADERS.length).getValues();
}

function rowToObject_(row) {
  return {
    record_type: row[0],
    page: row[1],
    line_id: row[2],
    line_number: row[3],
    status: row[4],
    anchor_y: row[5],
    category: row[6],
    note: row[7],
    reviewed_fingerprint: row[8],
    block_action: row[9],
    block_start_line: row[10],
    block_end_line: row[11],
    page_signed_off: row[12],
    page_signed_off_at: row[13],
    reviewer_name: row[14],
    updated_at: row[15],
  };
}

function objectToRow_(record) {
  return [
    record.record_type || 'line',
    record.page || '',
    record.line_id || '',
    record.line_number || '',
    record.status || 'pending',
    record.anchor_y === null || typeof record.anchor_y === 'undefined' ? '' : record.anchor_y,
    record.category || '',
    record.note || '',
    record.reviewed_fingerprint || '',
    record.block_action || '',
    record.block_start_line === null || typeof record.block_start_line === 'undefined' ? '' : record.block_start_line,
    record.block_end_line === null || typeof record.block_end_line === 'undefined' ? '' : record.block_end_line,
    record.page_signed_off || '',
    record.page_signed_off_at || '',
    record.reviewer_name || '',
    record.updated_at || new Date().toISOString(),
  ];
}

function writeAllRows_(sheet, records) {
  sheet.clearContents();
  ensureHeaders_(sheet);
  if (!records.length) {
    return;
  }
  const rows = records.map(objectToRow_);
  sheet.getRange(2, 1, rows.length, HEADERS.length).setValues(rows);
}

function loadReviewState_() {
  const sheet = openSheet_();
  const rows = getRows_(sheet).map(rowToObject_);
  const lineReviews = [];
  const pageSignOffs = {};
  let reviewerName = '';
  let latestUpdatedAt = '';

  rows.forEach(function (row) {
    if (!latestUpdatedAt || String(row.updated_at || '') > latestUpdatedAt) {
      latestUpdatedAt = String(row.updated_at || '');
    }
    if (row.reviewer_name && !reviewerName) {
      reviewerName = String(row.reviewer_name);
    }
    if (row.record_type === 'page_signoff') {
      const normalizedPageId = 'page-' + String(row.page).padStart(3, '0');
      pageSignOffs[normalizedPageId] = {
        page: row.page,
        signedOffAt: row.page_signed_off_at || row.updated_at || '',
      };
      return;
    }
    lineReviews.push({
      page: row.page,
      lineId: row.line_id,
      lineNumber: row.line_number,
      anchorY: row.anchor_y === '' ? null : Number(row.anchor_y),
      status: row.status || 'pending',
      category: row.category || '',
      note: row.note || '',
      reviewedFingerprint: row.reviewed_fingerprint || '',
      blockAction: row.block_action || '',
      blockStartLine: row.block_start_line === '' ? null : Number(row.block_start_line),
      blockEndLine: row.block_end_line === '' ? null : Number(row.block_end_line),
    });
  });

  return {
    reviewerName: reviewerName,
    updatedAt: latestUpdatedAt,
    lineReviews: lineReviews,
    pageSignOffs: pageSignOffs,
  };
}

function savePageReview_(payload) {
  const sheet = openSheet_();
  const existing = getRows_(sheet).map(rowToObject_);
  const keep = [];
  const targetPage = Number(payload.page);

  existing.forEach(function (row) {
    if (Number(row.page) !== targetPage) {
      keep.push(row);
    }
  });

  const updatedAt = new Date().toISOString();
  const reviewerName = payload.reviewerName || '';
  const lineRecords = (payload.lineReviews || []).map(function (review) {
    return {
      record_type: 'line',
      page: review.page,
      line_id: review.lineId,
      line_number: review.lineNumber,
      status: review.status || 'pending',
      anchor_y: typeof review.anchorY === 'number' ? review.anchorY : '',
      category: review.category || '',
      note: review.note || '',
      reviewed_fingerprint: review.reviewedFingerprint || '',
      block_action: review.blockAction || '',
      block_start_line: typeof review.blockStartLine === 'number' ? review.blockStartLine : '',
      block_end_line: typeof review.blockEndLine === 'number' ? review.blockEndLine : '',
      reviewer_name: reviewerName,
      updated_at: updatedAt,
    };
  });

  if (payload.pageSignOff) {
    lineRecords.push({
      record_type: 'page_signoff',
      page: targetPage,
      line_id: '',
      line_number: '',
      status: '',
      anchor_y: '',
      category: '',
      note: '',
      reviewed_fingerprint: '',
      block_action: '',
      block_start_line: '',
      block_end_line: '',
      page_signed_off: true,
      page_signed_off_at: payload.pageSignOff.signedOffAt || updatedAt,
      reviewer_name: reviewerName,
      updated_at: updatedAt,
    });
  }

  writeAllRows_(sheet, keep.concat(lineRecords));
}

function saveAllReviews_(payload) {
  const sheet = openSheet_();
  const updatedAt = new Date().toISOString();
  const reviewerName = payload.reviewerName || '';
  const records = [];

  (payload.lineReviews || []).forEach(function (review) {
    records.push({
      record_type: 'line',
      page: review.page,
      line_id: review.lineId,
      line_number: review.lineNumber,
      status: review.status || 'pending',
      anchor_y: typeof review.anchorY === 'number' ? review.anchorY : '',
      category: review.category || '',
      note: review.note || '',
      reviewed_fingerprint: review.reviewedFingerprint || '',
      block_action: review.blockAction || '',
      block_start_line: typeof review.blockStartLine === 'number' ? review.blockStartLine : '',
      block_end_line: typeof review.blockEndLine === 'number' ? review.blockEndLine : '',
      reviewer_name: reviewerName,
      updated_at: updatedAt,
    });
  });

  Object.keys(payload.pageSignOffs || {}).forEach(function (key) {
    const signoff = payload.pageSignOffs[key];
    records.push({
      record_type: 'page_signoff',
      page: signoff.page,
      line_id: '',
      line_number: '',
      status: '',
      anchor_y: '',
      category: '',
      note: '',
      reviewed_fingerprint: '',
      block_action: '',
      block_start_line: '',
      block_end_line: '',
      page_signed_off: true,
      page_signed_off_at: signoff.signedOffAt || updatedAt,
      reviewer_name: reviewerName,
      updated_at: updatedAt,
    });
  });

  writeAllRows_(sheet, records);
}

function jsonResponse_(payload) {
  return ContentService
    .createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}
