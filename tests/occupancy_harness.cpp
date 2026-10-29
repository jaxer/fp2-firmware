
#include "occupancy.h"
#include <cassert>
#include <iostream>
using namespace fp2_wire;
void isolated_boundaries(const Frame &original) {
  Occupancy model(100); Frame f=original;
  assert(!model.room().known);
  for (unsigned i=0;i<=31;++i) assert(!model.zone(i).known);
  // Isolated in-memory mutations of captured status; never sent anywhere.
  f.operation=5; f.payload={1,4,0,1};
  assert(model.ingest(f,0xfffffff0u));
  assert(!model.tick(0x53u)); // elapsed99 across wrap
  assert(model.tick(0x54u)); // elapsed100
  assert(!model.room().known && model.room().occupied);
  assert(model.ingest(f,200));
  assert(model.ingest(f,250)); // repeated report refreshes age
  assert(!model.tick(349)); assert(model.tick(350));
  f.payload={1,0x42,1,30,1};
  assert(model.ingest(f,400) && model.zone(30).known && model.zone(30).occupied);
  assert(!model.zone(1).known && !model.zone(29).known);
  model.invalidate(); assert(!model.zone(30).known && !model.room().known);
  assert(model.ingest(f,401));
  for (unsigned op : {1u,2u,3u,6u,255u}) {
    Frame bad=f; bad.operation=op; assert(!model.ingest(bad,500));
  }
  for (unsigned id : {0u,31u,255u}) {
    Frame bad=f; bad.payload[3]=id; assert(!model.ingest(bad,500));
  }
  for (unsigned status : {2u,255u}) {
    Frame bad=f; bad.payload[4]=status; assert(!model.ingest(bad,500));
  }
  for (unsigned tag : {0u,2u,3u,4u,5u,6u,7u}) {
    Frame bad=f; bad.payload[2]=tag; assert(!model.ingest(bad,500));
  }
  Frame bad=f; bad.payload.pop_back(); assert(!model.ingest(bad,500));
  bad=f;bad.payload.push_back(0); assert(!model.ingest(bad,500));
  f.payload={1,3,0,0}; assert(!model.ingest(f,500));
  f.payload={1,0x15,1,30,4}; assert(!model.ingest(f,500));
  f.payload={1,4,0,2}; assert(!model.ingest(f,500));
  f.payload={1,4,4,1}; assert(!model.ingest(f,500));
  assert(model.zone(30).updated_ms==401); // rejects do not refresh state
  Occupancy timeless; f.payload={1,0x42,1,1,1};
  assert(timeless.ingest(f,0)); assert(!timeless.tick(0xffffffffu));
  assert(timeless.zone(1).known && !timeless.room().known);
  timeless.invalidate(); assert(!timeless.zone(1).known);
  // op4 uses the same authoritative grammar; room and zones are independent.
  f.operation=4; f.payload={1,4,0,0};
  assert(timeless.ingest(f,20) && timeless.room().known && !timeless.room().occupied);
  assert(!timeless.zone(1).known);
}
int main() {
  Parser parser; Occupancy model; Frame f; char byte; unsigned now=0; bool tested=false;
  while (std::cin.get(byte)) {
    if (!parser.feed(static_cast<uint8_t>(byte),f)) continue;
    ++now;
    if (!tested) { isolated_boundaries(f); tested=true; }
    if (!model.ingest(f,now)) continue;
    if (f.payload[1]==4) std::cout << "R " << model.room().occupied << "\n";
    else {
      unsigned id=f.payload[3];
      std::cout << "Z " << id << " " << model.zone(id).occupied << "\n";
    }
  }
  assert(tested);
}
