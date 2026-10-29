
#include "target_zones.h"
#include <cassert>
#include <iostream>
using namespace fp2_wire;
void boundary_tests(Frame original) {
  TargetZones m; std::array<uint8_t,40> grid{};assert(!m.snapshot_known());
  for (size_t row=0;row<20;++row)grid[2*row]=255;
  assert(!m.configure(0,grid) && !m.configure(31,grid));
  assert(m.configure(30,grid)); assert(!m.zone(30).known && !m.zone(1).known);
  assert(!m.zone(0).known && !m.zone(255).known);
  // All local mutations below are isolated unit inputs, never transmitted.
  Frame f=original; f.operation=5; f.payload.resize(20);
  f.payload[0]=1;f.payload[1]=0x17;f.payload[2]=6;
  f.payload[3]=0;f.payload[4]=15;f.payload[5]=1;
  auto point=[&](int a,int b,uint8_t flag) {
    f.payload[7]=(a>>8)&255;f.payload[8]=a&255;
    f.payload[9]=(b>>8)&255;f.payload[10]=b&255;f.payload[17]=flag;
  };
  point(100,100,0); assert(m.ingest(f,10));
  assert(m.zone(30).known && m.zone(30).occupied);
  assert(m.snapshot_known()&&m.latest_snapshot().targets.size()==1);
  assert(m.latest_snapshot().targets[0].a_hundredths==100);
  point(0,100,0); assert(m.ingest(f,20));assert(!m.zone(30).known);
  point(100,100,255); assert(m.ingest(f,30));assert(!m.zone(30).known);
  point(-100,100,255); assert(m.ingest(f,40));
  assert(m.zone(30).known && !m.zone(30).occupied);
  point(100,100,1);assert(m.ingest(f,50));assert(m.zone(30).known && !m.zone(30).occupied);
  point(400,100,0);assert(m.ingest(f,60));assert(!m.zone(30).known);
  point(100,0,0);assert(m.ingest(f,70));assert(!m.zone(30).known);
  point(100,-10,0);assert(m.ingest(f,80));assert(m.zone(30).known && !m.zone(30).occupied);
  point(100,100,0);assert(m.ingest(f,90));
  Frame good=f;
  for (unsigned op:{1u,2u,3u,4u,6u}) {f=good;f.operation=op;assert(!m.ingest(f,100));}
  for (unsigned tag:{0u,1u,2u,3u,4u,5u,7u}) {f=good;f.payload[2]=tag;assert(!m.ingest(f,100));}
  f=good;f.payload[4]++;assert(!m.ingest(f,100));
  f=good;f.payload.pop_back();assert(!m.ingest(f,100));
  f=good;f.payload.push_back(0);assert(!m.ingest(f,100));
  assert(m.zone(30).updated_ms==90 && m.zone(30).occupied);
  assert(m.snapshot_known()&&m.latest_snapshot().targets[0].a_hundredths==100);
  // Explicit32target MVPbound, with no out-of-bounds access.
  f=good;f.payload.resize(6+14*32,0);f.payload[3]=1;f.payload[4]=193;f.payload[5]=32;
  assert(m.ingest(f,110));
  f.payload.resize(6+14*33,0);f.payload[3]=1;f.payload[4]=207;f.payload[5]=33;
  assert(!m.ingest(f,120));assert(m.zone(30).updated_ms==110&&!m.zone(30).known);
  assert(m.snapshot_known()&&m.latest_snapshot().targets.size()==33);
  // Definite eligible target overrides a separate ambiguous candidate.
  f=good;f.payload.insert(f.payload.end(),good.payload.begin()+6,good.payload.end());
  f.payload[4]=29;f.payload[5]=2;f.payload[17]=255;
  assert(m.ingest(f,130));assert(m.zone(30).known && m.zone(30).occupied);
  // Explicit roomempty clears only configuredzone; roomoccupied never fills it.
  f=good;f.operation=4;f.payload={1,4,0,0};assert(m.ingest(f,140));
  assert(m.zone(30).known && !m.zone(30).occupied && m.zone(30).updated_ms==140);
  assert(!m.snapshot_known()&&m.latest_snapshot().targets.size()==2);
  f.payload[3]=1;assert(m.ingest(f,150));assert(m.zone(30).updated_ms==140);
  f.payload[3]=2;assert(!m.ingest(f,160));
  assert(m.ingest(good,170)&&m.snapshot_known());
  m.invalidate();assert(!m.zone(30).known&&!m.snapshot_known());
  assert(m.latest_snapshot().targets.size()==1);
  assert(m.configure(30,grid));assert(!m.zone(30).known);
}
int main() {
  TargetZones model; std::array<uint8_t,40>a{},b{};
  for(size_t r=0;r<20;++r){a[2*r]=255;b[2*r+1]=255;}
  assert(model.configure(1,a) && model.configure(2,b));
  Parser parser;Frame frame;char byte;uint32_t now=0;bool checked=false;
  while(std::cin.get(byte)) {
    if(!parser.feed(static_cast<uint8_t>(byte),frame))continue;
    if(!checked){boundary_tests(frame);checked=true;}
    assert(model.ingest(frame,++now));
    const auto &x=model.zone(1);const auto &y=model.zone(2);
    std::cout<<x.known<<" "<<x.occupied<<" "<<y.known<<" "<<y.occupied<<"\n";
  }
  assert(checked);
}
