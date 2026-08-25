import httpx2


LIGHT_IDS = ('8a94b76b-eb9f-42fb-8b58-8c8701a80283', 
             '0c836d0d-ad3e-4527-802b-b5d0911b7b33', 
             'e8ff6285-fc12-44da-aa8e-c5f98ec167dd',
             '0fcfc949-4034-48f3-9f1d-fcba8bd31319',
             '228a2039-ed8c-4e27-b36d-13db9758db22',
             '217d73ed-695a-42f1-bbc1-20cf69c11ae2',)

class HueClient:
    def __init__(self, bridge_ip: str, app_key: str):
        self._client = httpx2.AsyncClient(
            base_url=f"https://{bridge_ip}/clip/v2",
            headers={'hue-application-key': app_key},
            verify=False,
            timeout=10.0,
        )

    async def set_light(self, light_id: str, on: bool):
        resp = await self._client.put(
            f'/resource/light/{light_id}',
            json={'on': {'on': on}},
        )
        resp.raise_for_status()

    async def set_all_lights(self, on: bool):
        for light_id in LIGHT_IDS:
            await self.set_light(light_id, on)

    async def aclose(self) -> None:
        await self._client.aclose()