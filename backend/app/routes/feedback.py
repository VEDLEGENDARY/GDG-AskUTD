"""Feedback endpoint."""
from fastapi import APIRouter, HTTPException, Request, Response, status

from ..schemas import FeedbackRequest

router = APIRouter()


@router.post("/feedback", status_code=status.HTTP_204_NO_CONTENT)
def feedback(body: FeedbackRequest, request: Request) -> Response:
    saved = request.app.state.db.save_feedback(request.app.state.settings.database_path,
                                                body.request_id, body.rating, body.comment)
    if not saved:
        raise HTTPException(status_code=404, detail={"code": "request_not_found",
                                                     "message": "No chat request exists with that request_id."})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
