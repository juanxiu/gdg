import uuid
from datetime import datetime
from typing import Optional
from app.db.firestore import get_collection
from app.models.profile import ProfileCreateRequest, ProfileResponse, ProfileUpdateRequest, CustomWeights


class ProfileService:
    """건강 프로필 Firestore CRUD 서비스"""

    def __init__(self):
        self.collection = get_collection("profiles")

    async def create(self, user_id: str, request: ProfileCreateRequest) -> dict:
        profile_id = f"p_{uuid.uuid4().hex[:8]}"
        
        # 가중치가 없으면 질환 정보를 보고 기본 가중치 자동 생성 (간략 구현)
        # 실제로는 RiskScorer.resolve_weights() 등을 활용
        auto_weights = CustomWeights(
            pm25=2.5 if request.conditions.respiratory.enabled else 1.0,
            temperature=3.0 if request.conditions.heatVulnerable.enabled else 1.0,
            pollen=3.0 if request.conditions.allergyPollen.enabled else 1.0,
            slope=2.0 if request.conditions.cardiovascular.enabled else 1.0,
            shade=2.0 if request.conditions.heatVulnerable.enabled else 1.0
        )

        profile_data = {
            "profileId": profile_id,
            "userId": user_id,
            "displayName": request.displayName,
            "age": request.age,
            "conditions": request.conditions.model_dump(),
            "customWeights": (request.customWeights or auto_weights).model_dump(),
            "guardianId": request.guardianId,
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow()
        }

        await self.collection.document(profile_id).set(profile_data)
        
        return {
            "profileId": profile_id,
            "autoWeights": auto_weights
        }

    async def get(self, profile_id: str, user_id: str = None) -> Optional[ProfileResponse]:
        doc = await self.collection.document(profile_id).get()
        if not doc.exists:
            return None
        
        data = doc.to_dict()
        # 소유자 확인
        if user_id and data.get("userId") != user_id:
            return None
            
        return ProfileResponse(**data)

    async def update(self, profile_id: str, user_id: str, request: ProfileUpdateRequest) -> Optional[ProfileResponse]:
        doc_ref = self.collection.document(profile_id)
        doc = await doc_ref.get()
        if not doc.exists or doc.to_dict().get("userId") != user_id:
            return None

        update_data = request.model_dump(exclude_unset=True)
        update_data["updatedAt"] = datetime.utcnow()
        
        await doc_ref.update(update_data)
        
        updated_doc = await doc_ref.get()
        return ProfileResponse(**updated_doc.to_dict())

    async def delete(self, profile_id: str, user_id: str) -> bool:
        doc_ref = self.collection.document(profile_id)
        doc = await doc_ref.get()
        if not doc.exists or doc.to_dict().get("userId") != user_id:
            return False
            
        await doc_ref.delete()
        return True
