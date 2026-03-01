/**
 * 쿠팡 "상품준비중(INSTRUCT)" ↔ 구글시트 동기화 템플릿 (Apps Script)
 *
 * 동작:
 * 1) 쿠팡 INSTRUCT 주문 목록 조회
 * 2) 시트(A:주문ID, G:상태)와 비교
 * 3) 시트에만 남아있는 "상품준비중" 주문은 "준비해제(자동)"으로 변경
 *
 * 주의:
 * - 시트 컬럼은 아래 HEADERS 순서를 기준으로 합니다.
 * - 액세스키/시크릿키/벤더ID는 Script Properties에 저장하세요.
 */

const CONFIG = {
  SHEET_ID: '여기에_스프레드시트_ID',
  SHEET_NAME: '쿠팡주문관리',

  LOOKBACK_DAYS: 7,
  STATUS_PREPARING: '상품준비중',
  STATUS_RELEASED: '준비해제(자동)',

  COUPANG_BASE_URL: 'https://api-gateway.coupang.com',
  COUPANG_TIMEZONE: 'Asia/Seoul',
  SCRIPT_TIMEZONE: 'Asia/Seoul',

  // Script Properties에서 읽음
  COUPANG_ACCESS_KEY:
    PropertiesService.getScriptProperties().getProperty('COUPANG_ACCESS_KEY') || '',
  COUPANG_SECRET_KEY:
    PropertiesService.getScriptProperties().getProperty('COUPANG_SECRET_KEY') || '',
  COUPANG_VENDOR_ID:
    PropertiesService.getScriptProperties().getProperty('COUPANG_VENDOR_ID') || '',

  // A~M (프로젝트의 기존 주문 시트 구조와 동일)
  HEADERS: [
    '주문ID',
    '상품명',
    '수량',
    '수신자',
    '연락처',
    '주소',
    '상태',
    '주문일시',
    'SMS발송',
    'orderItemId',
    '송장번호',
    '택배사코드',
    '발송처리일시',
  ],
};

/**
 * 메인 실행 함수
 */
function syncCoupangPreparingOrdersToSheet() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) {
    throw new Error('이전 동기화가 아직 실행 중입니다.');
  }

  try {
    validateConfig_();

    const sheet = getOrderSheet_();
    ensureHeaders_(sheet);

    const instructOrders = fetchOrdersByStatus_('INSTRUCT', CONFIG.LOOKBACK_DAYS);
    const instructIdSet = new Set(
      instructOrders.map((x) => x.orderId).filter((x) => Boolean(x))
    );

    const lastRow = Math.max(sheet.getLastRow(), 1);
    const lastCol = Math.max(sheet.getLastColumn(), CONFIG.HEADERS.length);
    const allValues = sheet.getRange(1, 1, lastRow, lastCol).getValues();

    // 데이터 행(2행~)을 A~M 기준 길이로 패딩
    const rows = allValues.slice(1).map((row) => padRow_(row, CONFIG.HEADERS.length));

    const rowIndexByOrderId = new Map();
    for (let i = 0; i < rows.length; i += 1) {
      const orderId = String(rows[i][0] || '').trim(); // A열
      if (orderId && !rowIndexByOrderId.has(orderId)) {
        rowIndexByOrderId.set(orderId, i);
      }
    }

    let inserted = 0;
    let released = 0;
    let restored = 0;

    // 1) INSTRUCT 목록 upsert
    for (let i = 0; i < instructOrders.length; i += 1) {
      const order = instructOrders[i];
      if (!order.orderId) continue;

      const rowIndex = rowIndexByOrderId.get(order.orderId);
      if (rowIndex === undefined) {
        rows.push(orderToSheetRow_(order));
        rowIndexByOrderId.set(order.orderId, rows.length - 1);
        inserted += 1;
        continue;
      }

      const row = rows[rowIndex];
      const prevStatus = String(row[6] || '').trim(); // G열
      if (prevStatus !== CONFIG.STATUS_PREPARING) {
        row[6] = CONFIG.STATUS_PREPARING;
        restored += 1;
      }

      // 기존 데이터 보존 우선. 비어있는 기본 필드만 보강.
      if (!String(row[1] || '').trim() && order.productName) row[1] = order.productName; // B
      if (!String(row[2] || '').trim() && order.quantity) row[2] = order.quantity; // C
      if (!String(row[3] || '').trim() && order.receiverName) row[3] = order.receiverName; // D
      if (!String(row[4] || '').trim() && order.phone) row[4] = order.phone; // E
      if (!String(row[5] || '').trim() && order.address) row[5] = order.address; // F
      if (!String(row[7] || '').trim() && order.orderedAt) row[7] = order.orderedAt; // H
      if (!String(row[9] || '').trim() && order.shipmentBoxId) row[9] = order.shipmentBoxId; // J
    }

    // 2) 시트에만 남은 "상품준비중" 행은 상태 해제
    for (let i = 0; i < rows.length; i += 1) {
      const row = rows[i];
      const orderId = String(row[0] || '').trim(); // A열
      const status = String(row[6] || '').trim(); // G열

      if (!orderId) continue;
      if (status !== CONFIG.STATUS_PREPARING) continue;

      if (!instructIdSet.has(orderId)) {
        row[6] = CONFIG.STATUS_RELEASED;
        released += 1;
      }
    }

    // A~M 영역 일괄 반영
    if (rows.length > 0) {
      sheet.getRange(2, 1, rows.length, CONFIG.HEADERS.length).setValues(rows);
    }

    Logger.log(
      '[Coupang Sync] INSTRUCT=%s, 신규추가=%s, 복구=%s, 준비해제=%s',
      instructOrders.length,
      inserted,
      restored,
      released
    );
  } finally {
    lock.releaseLock();
  }
}

/**
 * 5분 트리거 설치 (기존 동일 핸들러 트리거는 삭제 후 재생성)
 */
function installSyncTriggerEvery5Minutes() {
  const handler = 'syncCoupangPreparingOrdersToSheet';
  const triggers = ScriptApp.getProjectTriggers();
  for (let i = 0; i < triggers.length; i += 1) {
    if (triggers[i].getHandlerFunction() === handler) {
      ScriptApp.deleteTrigger(triggers[i]);
    }
  }
  ScriptApp.newTrigger(handler).timeBased().everyMinutes(5).create();
}

/**
 * 스프레드시트 메뉴
 */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Coupang Sync')
    .addItem('지금 동기화', 'syncCoupangPreparingOrdersToSheet')
    .addItem('5분 트리거 설치', 'installSyncTriggerEvery5Minutes')
    .addToUi();
}

// --------------------------
// Coupang API
// --------------------------

function fetchOrdersByStatus_(status, days) {
  const now = new Date();
  const from = new Date(now.getTime() - days * 24 * 60 * 60 * 1000);
  const path = '/v2/providers/openapi/apis/api/v5/vendors/' + CONFIG.COUPANG_VENDOR_ID + '/ordersheets';

  const baseParams = {
    createdAtFrom: formatCoupangDateWithTz_(from),
    createdAtTo: formatCoupangDateWithTz_(now),
    status: status,
    maxPerPage: 50,
  };

  const allOrders = [];
  const seenTokens = new Set();
  let nextToken = '';

  for (let i = 0; i < 30; i += 1) {
    const params = Object.assign({}, baseParams);
    if (nextToken) params.nextToken = nextToken;

    const result = coupangRequest_('GET', path, params);
    const parsed = parseOrderPage_(result);

    for (let j = 0; j < parsed.orders.length; j += 1) {
      const normalized = normalizeOrder_(parsed.orders[j]);
      if (normalized.orderId) allOrders.push(normalized);
    }

    if (!parsed.nextToken || seenTokens.has(parsed.nextToken)) {
      break;
    }
    seenTokens.add(parsed.nextToken);
    nextToken = parsed.nextToken;
  }

  // 중복 제거(orderId 기준)
  const deduped = [];
  const seenOrderIds = new Set();
  for (let i = 0; i < allOrders.length; i += 1) {
    const id = allOrders[i].orderId;
    if (!id || seenOrderIds.has(id)) continue;
    seenOrderIds.add(id);
    deduped.push(allOrders[i]);
  }

  return deduped;
}

function coupangRequest_(method, path, params) {
  const query = buildQueryString_(params);
  const url = CONFIG.COUPANG_BASE_URL + path + (query ? '?' + query : '');
  const headers = makeCoupangHeaders_(method, path, query);

  const res = UrlFetchApp.fetch(url, {
    method: method.toLowerCase(),
    headers: headers,
    muteHttpExceptions: true,
  });

  const code = res.getResponseCode();
  const text = res.getContentText();
  if (code < 200 || code >= 300) {
    throw new Error('[Coupang API] ' + code + ' ' + text.slice(0, 500));
  }

  return JSON.parse(text);
}

function makeCoupangHeaders_(method, path, query) {
  const signedDate = Utilities.formatDate(new Date(), 'UTC', "yyMMdd'T'HHmmss'Z'");
  const message = signedDate + method.toUpperCase() + path + (query || '');
  const bytes = Utilities.computeHmacSha256Signature(message, CONFIG.COUPANG_SECRET_KEY);
  const signature = toHex_(bytes);

  const authorization =
    'CEA algorithm=HmacSHA256, access-key=' +
    CONFIG.COUPANG_ACCESS_KEY +
    ', signed-date=' +
    signedDate +
    ', signature=' +
    signature;

  return {
    Authorization: authorization,
    'Content-Type': 'application/json;charset=UTF-8',
  };
}

function parseOrderPage_(result) {
  const data = result && result.data !== undefined ? result.data : [];
  let orders = [];
  let nextToken = '';

  if (Array.isArray(data)) {
    orders = data;
    nextToken = String(result.nextToken || '');
  } else if (data && typeof data === 'object') {
    orders = data.content || data.data || [];
    nextToken = String(data.nextToken || result.nextToken || '');
  }

  return { orders: orders, nextToken: nextToken };
}

function normalizeOrder_(order) {
  const receiver = order.receiver || {};
  const item = (order.orderItems && order.orderItems[0]) || {};

  return {
    orderId: String(order.orderId || '').trim(),
    shipmentBoxId: String(order.shipmentBoxId || '').trim(),
    productName: String(item.vendorItemName || item.itemName || item.productName || '').trim(),
    quantity: String(item.shippingCount || item.orderCount || item.quantity || '').trim(),
    receiverName: String(receiver.name || '').trim(),
    phone: String(receiver.safeNumber || receiver.phone || '').trim(),
    address: buildAddress_(receiver),
    orderedAt: String(order.orderedAt || '').trim(),
  };
}

// --------------------------
// Sheet helpers
// --------------------------

function getOrderSheet_() {
  const ss = SpreadsheetApp.openById(CONFIG.SHEET_ID);
  const sheet = ss.getSheetByName(CONFIG.SHEET_NAME);
  if (!sheet) {
    throw new Error('시트를 찾을 수 없습니다: ' + CONFIG.SHEET_NAME);
  }
  return sheet;
}

function ensureHeaders_(sheet) {
  const range = sheet.getRange(1, 1, 1, CONFIG.HEADERS.length);
  const current = range.getValues()[0];
  let changed = false;

  for (let i = 0; i < CONFIG.HEADERS.length; i += 1) {
    if (current[i] !== CONFIG.HEADERS[i]) {
      current[i] = CONFIG.HEADERS[i];
      changed = true;
    }
  }

  if (changed || sheet.getLastRow() === 0) {
    range.setValues([current]);
  }
}

function orderToSheetRow_(order) {
  return [
    order.orderId || '',
    order.productName || '',
    order.quantity || '',
    order.receiverName || '',
    order.phone || '',
    order.address || '',
    CONFIG.STATUS_PREPARING,
    order.orderedAt || '',
    '',
    order.shipmentBoxId || '',
    '',
    '',
    '',
  ];
}

function padRow_(row, length) {
  const copy = row.slice(0, length);
  while (copy.length < length) copy.push('');
  return copy;
}

// --------------------------
// Utility
// --------------------------

function validateConfig_() {
  const missing = [];

  if (!CONFIG.SHEET_ID || CONFIG.SHEET_ID === '여기에_스프레드시트_ID') {
    missing.push('CONFIG.SHEET_ID');
  }
  if (!CONFIG.COUPANG_ACCESS_KEY) missing.push('ScriptProperty: COUPANG_ACCESS_KEY');
  if (!CONFIG.COUPANG_SECRET_KEY) missing.push('ScriptProperty: COUPANG_SECRET_KEY');
  if (!CONFIG.COUPANG_VENDOR_ID) missing.push('ScriptProperty: COUPANG_VENDOR_ID');

  if (missing.length > 0) {
    throw new Error('설정 누락: ' + missing.join(', '));
  }
}

function buildQueryString_(params) {
  if (!params) return '';
  const keys = Object.keys(params)
    .filter((k) => params[k] !== undefined && params[k] !== null && String(params[k]) !== '')
    .sort();
  const parts = [];
  for (let i = 0; i < keys.length; i += 1) {
    const key = keys[i];
    parts.push(encodeURIComponent(key) + '=' + encodeURIComponent(String(params[key])));
  }
  return parts.join('&');
}

function formatCoupangDateWithTz_(date) {
  const ymd = Utilities.formatDate(date, CONFIG.COUPANG_TIMEZONE, 'yyyy-MM-dd');
  const z = Utilities.formatDate(date, CONFIG.COUPANG_TIMEZONE, 'Z'); // +0900
  const offset = z.slice(0, 3) + ':' + z.slice(3);
  return ymd + offset;
}

function buildAddress_(receiver) {
  const parts = [];
  if (receiver.postCode) parts.push('(' + String(receiver.postCode).trim() + ')');
  if (receiver.addr1) parts.push(String(receiver.addr1).trim());
  if (receiver.addr2) parts.push(String(receiver.addr2).trim());
  return parts.join(' ').trim();
}

function toHex_(bytes) {
  let out = '';
  for (let i = 0; i < bytes.length; i += 1) {
    const v = bytes[i] < 0 ? bytes[i] + 256 : bytes[i];
    const h = v.toString(16);
    out += h.length === 1 ? '0' + h : h;
  }
  return out;
}

