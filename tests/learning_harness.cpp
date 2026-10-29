
#include "learning.h"
// All Frames below are synthetic isolated protocol fixtures.
#include <cassert>
#include <iostream>
using namespace fp2_wire;

bool equal(const Learning::State&a,const Learning::State&b){return a.action==b.action&&a.status==b.status&&a.acknowledged==b.acknowledged&&a.ack_failed==b.ack_failed&&a.background_complete==b.background_complete&&a.candidate_available==b.candidate_available&&a.ack_status==b.ack_status&&a.ack_sequence==b.ack_sequence&&a.candidate==b.candidate;}
int main(){
 const Frame synthetic_start{9,2,{1,0x13,4,1}},synthetic_ack{9,3,{1,0x13,0,0}},synthetic_done{4,5,{1,0x13,4,1}};
 Learning l;Frame request{99,99,{99}};
 assert(l.state().status==Learning::Status::UNKNOWN);
 assert(!l.start(Learning::Action::NONE,1,0,100,request));assert(request.payload==std::vector<uint8_t>{99});
 assert(!l.start(Learning::Action::BACKGROUND,1,0,0,request));
 assert(l.start(Learning::Action::BACKGROUND,synthetic_start.sequence,0,100,request));
 assert(request.operation==synthetic_start.operation && request.payload==synthetic_start.payload);
 Frame unchanged=request;assert(!l.start(Learning::Action::AUTO_EDGE,2,1,100,request));assert(request.payload==unchanged.payload);
 assert(l.observe(synthetic_ack));assert(l.state().acknowledged && l.state().status==Learning::Status::AWAITING_COMPLETION);
 l.expire(99);assert(l.state().status==Learning::Status::AWAITING_COMPLETION);
 l.expire(100);assert(l.state().status==Learning::Status::OUTCOME_UNKNOWN);
 assert(!l.start(Learning::Action::BACKGROUND,2,101,100,request)); // No unsafe automatic retry.
 assert(l.observe(synthetic_done));assert(l.state().status==Learning::Status::COMPLETED&&l.state().background_complete);
 assert(l.start(Learning::Action::AUTO_EDGE,7,200,100,request));
 assert(request.operation==2 && request.payload==std::vector<uint8_t>({1,0x50,4,1}));
 // A background report cannot complete an automatic-edge action.
 assert(l.observe(synthetic_done));assert(l.state().status==Learning::Status::AWAITING_COMPLETION);
 Frame candidate{17,5,{1,0x49,6,0,40}};
 for(unsigned i=0;i<40;++i)candidate.payload.push_back(uint8_t(i*7)); // Isolated bitmap fixture only.
 for(unsigned fault=0;fault<5;++fault){auto bad=candidate;
  if(fault==0)bad.payload[2]=5;
  if(fault==1)bad.payload[4]=39;
  if(fault==2)bad.payload.pop_back();
  if(fault==3)bad.payload.push_back(0);
  if(fault==4)bad.operation=4;
  const auto before=l.state();assert(!l.observe(bad));assert(equal(before,l.state()));
 }
 assert(l.observe(candidate));assert(l.state().status==Learning::Status::COMPLETED && l.state().candidate_available);
 for(unsigned i=0;i<40;++i)assert(l.state().candidate[i]==candidate.payload[5+i]);
 // Receipt types/attribute and false completion are strict; malformed keeps output.
 Learning strict;assert(strict.start(Learning::Action::BACKGROUND,synthetic_ack.sequence,0,100,request));
 for(unsigned fault=0;fault<5;++fault){auto bad=synthetic_ack;
  if(fault==0)bad.payload[1]++;
  if(fault==1)bad.payload[2]=4;
  if(fault==2)bad.payload.pop_back();
  if(fault==3)bad.payload.push_back(0);
  if(fault==4)bad.operation=4;
  auto before=strict.state();assert(!strict.observe(bad));assert(equal(before,strict.state()));
 }
 auto false_done=synthetic_done;false_done.payload[3]=0;auto before=strict.state();
 assert(!strict.observe(false_done)&&equal(before,strict.state()));
 auto reject=synthetic_ack;reject.payload[3]=1;assert(strict.observe(reject));
 assert(strict.state().ack_failed&&strict.state().status==Learning::Status::OUTCOME_UNKNOWN);
 // Report observation at startup cannot reconstruct a prior action's progress.
 Learning startup;assert(startup.observe(candidate));assert(startup.state().status==Learning::Status::UNKNOWN);
 assert(startup.state().candidate_available);
 Learning wrap;assert(wrap.start(Learning::Action::AUTO_EDGE,1,UINT32_MAX-49,100,request));
 wrap.expire(49);assert(wrap.state().status==Learning::Status::AWAITING_COMPLETION);
 wrap.expire(50);assert(wrap.state().status==Learning::Status::OUTCOME_UNKNOWN);
 std::cout<<"learning action checks passed\n";
}
