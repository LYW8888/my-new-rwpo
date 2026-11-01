const test = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const cities = JSON.parse(readFileSync(new URL('../data/locations.json', `file://${__filename}`))).cities;

test('listed cities and safe aliases match without guessing partial addresses', async () => {
  const {matchCity} = await import('../frontend/src/location-state.js');
  for (const city of cities) assert.equal(matchCity(`${city.name}市`, cities)?.id, city.id);
  assert.equal(matchCity(' 臺 北 市 ', cities)?.id, 'taipei');
  for (const value of ['', '杭州附近', '杭州市西湖区', '河南南阳']) assert.equal(matchCity(value, cities), undefined);
});

test('changing place invalidates old coordinates and matches carry timezone and centre', async () => {
  const {withPlace} = await import('../frontend/src/location-state.js');
  const initial = {place:'', zone:'Asia/Shanghai', locationId:'', longitude:''};
  const taipei = withPlace(initial, '台北', cities);
  assert.equal(taipei.zone, 'Asia/Taipei');
  assert.equal(taipei.longitude, '121.57');
  const manual = {...taipei, longitude:'121.56', zoneManual:true, zone:'Asia/Hong_Kong'};
  assert.deepEqual(withPlace(manual, '臺北市', cities), {...manual, place:'臺北市'});
  const next = withPlace(manual, '成都', cities);
  assert.equal(next.longitude, '104.07'); assert.equal(next.zone, 'Asia/Shanghai');
  const unmatched = withPlace(taipei, '未收录地点', cities);
  assert.equal(unmatched.longitude, ''); assert.equal(unmatched.locationId, ''); assert.equal(unmatched.zone, 'Asia/Shanghai');
  const preservedZone = withPlace(manual, '', cities);
  assert.equal(preservedZone.longitude, ''); assert.equal(preservedZone.zone, 'Asia/Hong_Kong');
});

test('longitude display preserves zero and western coordinates', async () => {
  const {longitudeText} = await import('../frontend/src/location-state.js');
  assert.equal(longitudeText(0), '0°E'); assert.equal(longitudeText(-75.99), '75.99°W');
  assert.equal(longitudeText('120.16'), '120.16°E');
  assert.equal(longitudeText(''), '未填写经度'); assert.equal(longitudeText('NaN'), '未填写经度');
});
