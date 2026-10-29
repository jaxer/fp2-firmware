#include "factory_calibration.h"
#include <algorithm>
#include <cstring>
#include <vector>

namespace fp2_wire {
namespace {
constexpr size_t PAGE = 4096;
uint32_t le32(const uint8_t *p) {
  return uint32_t(p[0]) | uint32_t(p[1]) << 8 | uint32_t(p[2]) << 16 | uint32_t(p[3]) << 24;
}
uint16_t le16(const uint8_t *p) { return uint16_t(p[0]) | uint16_t(p[1]) << 8; }
// zlib.crc32(data,0xffffffff): internal reflected register starts0, final XORffffffff.
uint32_t update(uint32_t crc, const uint8_t *p, size_t n) {
  while (n--) {
    crc ^= *p++;
    for (unsigned bit = 0; bit < 8; ++bit) crc = (crc >> 1) ^ ((crc & 1) ? 0xedb88320u : 0u);
  }
  return crc;
}
bool entry_crc(const uint8_t *e) { return ~update(update(0, e, 4), e + 8, 24) == le32(e + 4); }
bool key_is(const uint8_t *e, const char *key) {
  const size_t n = std::strlen(key);
  return n < 16 && std::memcmp(e + 8, key, n) == 0 && e[8 + n] == 0;
}
struct Entry { const uint8_t *p; const uint8_t *page; size_t slot; };
bool inventory(const uint8_t *data, size_t len, std::vector<Entry> &entries, uint8_t &ns) {
  if (data == nullptr || len != 0x6000) return false;
  std::vector<uint32_t> sequences;
  for (size_t offset = 0; offset < len; offset += PAGE) {
    const uint8_t *page = data + offset;
    if (std::all_of(page, page + PAGE, [](uint8_t b) { return b == 0xff; })) continue;
    const uint32_t state = le32(page);
    if (page[8] != 0xfe || (state != 0xfffffffeu && state != 0xfffffffcu) ||
        ~update(0, page + 4, 24) != le32(page + 28)) return false;
    const uint32_t sequence = le32(page + 4);
    if (sequence == 0xffffffffu || std::find(sequences.begin(), sequences.end(), sequence) != sequences.end()) return false;
    sequences.push_back(sequence);
    for (size_t slot = 0; slot < 126;) {
      const unsigned state_bits = (page[32 + slot / 4] >> (2 * (slot % 4))) & 3;
      if (state_bits == 1) return false;  // incomplete/transitional entry
      if (state_bits != 2) { ++slot; continue; }
      const uint8_t *e = page + 64 + slot * 32;
      const size_t span = e[2];
      if (span == 0 || slot + span > 126 || !entry_crc(e)) return false;
      for (size_t part = 1; part < span; ++part)
        if (((page[32 + (slot + part) / 4] >> (2 * ((slot + part) % 4))) & 3) != 2) return false;
      entries.push_back({e, page, slot});
      slot += span;
    }
  }
  unsigned fac_count = 0;
  for (const auto &entry : entries) {
    const auto *e = entry.p;
    if (e[0] == 0 && key_is(e, "fac")) {
      if (e[1] != 1 || e[2] != 1 || e[24] == 0 || e[24] == 0xff) return false;
      ns = e[24]; ++fac_count;
    }
  }
  if (fac_count != 1) return false;
  for (const auto &entry : entries)
    if (entry.p[0] == 0 && entry.p[1] == 1 && entry.p[24] == ns && !key_is(entry.p, "fac")) return false;
  return true;
}

const uint8_t *blob_payload(const std::vector<Entry> &entries, uint8_t ns, const char *key, size_t length) {
  const Entry *blob = nullptr, *index = nullptr;
  for (const auto &entry : entries) {
    const auto *e = entry.p;
    if (e[0] != ns || !key_is(e, key)) continue;
    if (e[1] == 0x42 && blob == nullptr) blob = &entry;
    else if (e[1] == 0x48 && index == nullptr) index = &entry;
    else return nullptr;  // No guessed winner among written duplicates.
  }
  if (blob == nullptr || index == nullptr) return nullptr;
  const auto *b = blob->p, *i = index->p;
  if (b[2] != 2 || le16(b + 24) != length || i[2] != 1 || i[3] != 0xff ||
      le32(i + 24) != length || i[28] != 1 || i[29] != b[3]) return nullptr;
  const uint8_t *payload = b + 32;
  if (~update(0, payload, length) != le32(b + 28)) return nullptr;
  return payload;
}
int16_t signed16(const uint8_t *payload) {
  const uint16_t raw = le16(payload);
  return static_cast<int16_t>(raw < 0x8000u ? raw : int32_t(raw) - 65536);
}
}  // namespace

bool load_accel_corrections(const uint8_t *data, size_t len, std::array<int16_t, 3> &out) {
  std::vector<Entry> entries;
  uint8_t ns = 0;
  if (!inventory(data, len, entries, ns)) return false;
  std::array<int16_t, 3> result{};
  const char *keys[] = {"corr_x", "corr_y", "corr_z"};
  for (size_t axis = 0; axis < 3; ++axis) {
    const auto *payload = blob_payload(entries, ns, keys[axis], 2);
    if (payload == nullptr) return false;
    result[axis] = signed16(payload);
  }
  out = result;
  return true;
}

bool load_light_calibration(const uint8_t *data, size_t len, LightCalibration &out) {
  std::vector<Entry> entries;
  uint8_t ns = 0;
  if (!inventory(data, len, entries, ns)) return false;
  const char *keys[] = {"lux_low_k", "lux_low_b", "lux_high_k", "lux_high_b",
                        "lux_low_min", "lux_low_max", "lux_high_min", "lux_high_max"};
  const uint8_t *payloads[8];
  for (size_t key = 0; key < 8; ++key) {
    payloads[key] = blob_payload(entries, ns, keys[key], key < 4 ? 2 : 4);
    if (payloads[key] == nullptr) return false;
  }
  LightCalibration result;
  result.low_k = signed16(payloads[0]) / 1000.f;
  result.low_b = signed16(payloads[1]) / 10.f;
  result.high_k = signed16(payloads[2]) / 1000.f;
  result.high_b = signed16(payloads[3]) / 10.f;
  result.low_min = le32(payloads[4]);
  result.low_max = le32(payloads[5]);
  result.high_min = le32(payloads[6]);
  result.high_max = le32(payloads[7]);
  out = result;
  return true;
}
}  // namespace fp2_wire
