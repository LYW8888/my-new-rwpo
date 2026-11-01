// Match only listed city names, never guess coordinates from part of an address.
function cityKey(value) {
  return String(value || "").normalize("NFKC").replace(/\s/g, "").replaceAll("臺", "台").replace(/市$/, "");
}

export function matchCity(place, cities) {
  const key = cityKey(place);
  return key ? cities.find(city => cityKey(city.name) === key) : undefined;
}

export function withPlace(previous, place, cities) {
  const city = matchCity(place, cities);
  const before = matchCity(previous.place, cities);
  if (city && before?.id === city.id) return { ...previous, place };
  if (city) return {
    ...previous, place, zone: city.zone, zoneManual: false,
    locationId: city.id, longitude: String(city.longitude),
  };
  return {
    ...previous, place, locationId: "", longitude: "",
    zone: previous.locationId && !previous.zoneManual ? "Asia/Shanghai" : previous.zone,
  };
}

export function longitudeText(value) {
  if (value === "" || value == null || !Number.isFinite(Number(value))) return "未填写经度";
  const longitude = Number(value);
  return `${Math.abs(longitude)}°${longitude < 0 ? "W" : "E"}`;
}
