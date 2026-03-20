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
        
        # Use RiskScorer to generate standardized initial weights
        from app.services.risk_scorer import RiskScorer
        auto_weights_dict = RiskScorer.resolve_weights(request.conditions)
        auto_weights = CustomWeights(**auto_weights_dict)

        profile_data = {
            "profile_id": profile_id,
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
            "profile_id": profile_id,
            "autoWeights": auto_weights
        }

        doc_id = profile_id if profile_id != "default_profile" else f"p_default_{user_id[:8]}"
        doc = await self.collection.document(doc_id).get()
        
        # If profile doesn't exist and it's a default request, create one specifically for this user
        if not doc.exists:
            if profile_id == "default_profile" and user_id:
                from app.models.profile import HealthConditions, CustomWeights
                from app.services.risk_scorer import RiskScorer
                
                initial_conditions = HealthConditions()
                initial_weights = CustomWeights(**RiskScorer.resolve_weights(initial_conditions))
                
                default_data = {
                    "profile_id": doc_id,
                    "userId": user_id,
                    "displayName": "Default User",
                    "age": 70, 
                    "conditions": initial_conditions.model_dump(),
                    "customWeights": initial_weights.model_dump(),
                    "createdAt": datetime.utcnow(),
                    "updatedAt": datetime.utcnow()
                }
                await self.collection.document(doc_id).set(default_data)
                return ProfileResponse(**default_data)
            return None
        
        data = doc.to_dict()
        # 소유자 확인
        if user_id and data.get("userId") != user_id:
            return None
            
        return ProfileResponse(**data)

    async def get_by_user_id(self, user_id: str) -> Optional[ProfileResponse]:
        """user_id로 프로필 조회 (에이전트용). 없으면 default_profile 자동 생성."""
        query = self.collection.where("userId", "==", user_id).limit(1)
        docs = [doc async for doc in query.stream()]
        
        if docs:
            return ProfileResponse(**docs[0].to_dict())
        
        # 프로필이 없으면 기본 프로필 자동 생성
        return await self.get("default_profile", user_id)

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
