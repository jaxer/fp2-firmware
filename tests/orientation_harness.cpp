
#include "orientation.h"
#include <cassert>
#include <iostream>
using namespace fp2_wire;
using Batch=std::array<std::array<int16_t,3>,10>;
Batch batch(int16_t x,int16_t y,int16_t z){Batch b;for(auto &v:b)v={x,y,z};return b;}
int main(){
 const std::array<int16_t,3> zero{};
 // Analytic interior fixtures reviewed against source thresholds, not live data.
 const int16_t points[8][3]={{10,20,-1000},{10,-990,-1000},{10,1000,-990},
  {10,-1000,20},{10,1000,20},{10,20,1000},{10,-500,1000},{10,500,1000}};
 const uint16_t tilts[8]={2,46,46,89,89,1,27,27};
 for(uint8_t i=0;i<8;++i){
  Orientation m;assert(!m.angle_ready()&&!m.orientation_ready());
  assert(m.update(batch(points[i][0],points[i][1],points[i][2]),zero,100));
  assert(m.angle_ready()&&m.orientation_ready()&&m.direction()==i);
  assert(m.tilt()==tilts[i]&&m.last_update_ms()==100);
 }
 auto up=batch(10,20,-1000),invalid=batch(1000,900,800);
 Orientation unready;
 for(unsigned i=1;i<=29;++i){assert(unready.update(invalid,zero,i));assert(unready.angle_ready());assert(!unready.orientation_ready());}
 assert(unready.update(invalid,zero,30));assert(unready.orientation_ready()&&unready.direction()==8);
 assert(unready.update(up,zero,31));assert(unready.direction()==0);
 Orientation held;assert(held.update(up,zero,1));
 for(unsigned i=0;i<29;++i){assert(held.update(invalid,zero,2+i));assert(held.direction()==0);}
 assert(held.update(invalid,zero,31));assert(held.direction()==8);
 // All five departure-delayed classes: exact four holds/fifthaccept.
 for(uint8_t previous:{3,4,5,6,7}){
  Orientation m;assert(m.update(batch(points[previous][0],points[previous][1],points[previous][2]),zero,0));
  for(unsigned i=1;i<5;++i){assert(m.update(up,zero,i));assert(m.direction()==previous);}
  assert(m.update(up,zero,5));assert(m.direction()==0);
 }
 // The departure counter is not tied to one replacement direction.
 Orientation varying;assert(varying.update(batch(10,-1000,20),zero,0));
 for(unsigned i=0;i<5;++i){uint8_t candidate[]={0,1,2,6,7};auto p=points[candidate[i]];
  assert(varying.update(batch(p[0],p[1],p[2]),zero,i+1));assert(varying.direction()==(i==4?7:3));}
 // Transitions within3/6 and4/7 are delayed too.
 for(auto pair:std::array<std::array<uint8_t,2>,4>{{{{3,6}},{{6,3}},{{4,7}},{{7,4}}}}){
  Orientation m;auto a=points[pair[0]],b=points[pair[1]];
  assert(m.update(batch(a[0],a[1],a[2]),zero,0));
  for(unsigned i=1;i<=5;++i){assert(m.update(batch(b[0],b[1],b[2]),zero,i));assert(m.direction()==(i<5?pair[0]:pair[1]));}
 }
 // Invalid candidate clears departure counters; valid resets invalid streak.
 Orientation reset;assert(reset.update(batch(10,-1000,20),zero,0));
 for(unsigned i=1;i<5;++i)assert(reset.update(up,zero,i));
 assert(reset.update(invalid,zero,5));assert(reset.direction()==3);
 assert(reset.update(up,zero,6));assert(reset.direction()==3);
 for(unsigned i=0;i<28;++i)assert(reset.update(invalid,zero,7+i));
 assert(reset.direction()==3);assert(reset.update(up,zero,40));
 assert(reset.update(invalid,zero,41));assert(reset.direction()==3);
 // Mean equality guard precedes corrections, including exact-axis samples.
 Orientation guard;assert(guard.update(batch(1,1,2),{100,200,300},1));
 assert(guard.angle_ready()&&guard.tilt()==90&&!guard.orientation_ready());
 assert(guard.update(batch(0,0,1000),zero,2)&&guard.tilt()==90);
 // Signed integer division is towardzero: -9/10=>0 equals Ymean0.
 Batch fraction=batch(-1,0,1000);fraction[0][0]=0;
 assert(guard.update(fraction,zero,3)&&guard.tilt()==90);
 // Correction addition narrows to signed16 before angle calculation.
 Orientation narrow;assert(narrow.update(batch(10,1000,20),{0,32767,0},1));
 assert(narrow.direction()==3&&narrow.tilt()==90);
 // Input validation clears readiness; failures do not advance timestamp.
 auto bad=batch(10,20,1000);bad[5][0]=2048;
 assert(!narrow.update(bad,zero,2));assert(!narrow.angle_ready()&&!narrow.orientation_ready());
 assert(narrow.last_update_ms()==1);
 assert(!narrow.update(batch(0,0,0),zero,3));
 assert(!narrow.update(batch(1,2,3),{-1,-2,-3},4));
 assert(narrow.update(batch(-2048,2047,1000),zero,5));
 narrow.invalidate();assert(!narrow.angle_ready()&&!narrow.orientation_ready());
 assert(narrow.update(up,zero,6)&&narrow.direction()==0);
 std::cout<<"analytic orientation and debounce checks passed\n";
}
