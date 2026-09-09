import asyncio
from pathlib import Path
from pprint import pprint

from salus.config import NodeConfig
from salus.dispatch.state_machine import DispatchStateMachine
from salus.rag.index import KnowledgeIndex
from salus.agents.pipeline import DispatchPipeline
from simulation.generators import generate_zones, generate_resources

async def main():
    config = NodeConfig()
    
    print("==================================================")
    print("1. Initializing Salus State Machine & Resources")
    print("==================================================")
    sm = DispatchStateMachine()
    zones = generate_zones(3)
    resources = generate_resources(5)
    for z in zones:
        sm.zones[z.id] = z
    for r in resources:
        sm.resources[r.id] = r
    print(f"Registered {len(zones)} zones and {len(resources)} resources.")
        
    print("\n==================================================")
    print("2. Initializing ChromaDB RAG Index")
    print("==================================================")
    index = KnowledgeIndex(config.rag)
    index._ensure_initialized()
    ingested = index.ingest_directory(Path("data/protocols"))
    print(f"Ingested {ingested} protocol documents into RAG index.")
    
    print("\n==================================================")
    print("3. Executing 5-Agent Pipeline")
    print("==================================================")
    pipeline = DispatchPipeline(
        llm_config=config.llm,
        rag_config=config.rag,
        knowledge_index=index,
        state_machine=sm,
        icp_id="demo-icp"
    )
    
    incident_description = "A massive 7.2 magnitude earthquake has struck. Multiple buildings have collapsed in the commercial district, and there are reports of people trapped under rubble. The main access bridge has collapsed."
    zone_id = zones[0].id
    
    print(f"Incident: {incident_description}")
    print(f"Target Zone: {zones[0].name} (ID: {zone_id})")
    print("Running Damage Assessment -> Resource Match -> Protocol Lookup -> Routing -> Decision Synthesis...")
    
    order = await pipeline.run(
        incident_id="INC-EQ-001",
        zone_id=zone_id,
        incident_description=incident_description
    )
    
    print("\n==================================================")
    print("4. Pipeline Output (Ready for Commander Gate)")
    print("==================================================")
    print(order.model_dump_json(indent=2))

if __name__ == "__main__":
    asyncio.run(main())
