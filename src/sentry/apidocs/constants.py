from drf_spectacular.utils import OpenApiResponse

# 200
RESPONSE_SUCCESS = OpenApiResponse(description="Success")

# 201 - Created
RESPONSE_NO_CONTENT = OpenApiResponse(description="No Content")

# 202 - Accepted (not yet acted on fully)
RESPONSE_ACCEPTED = OpenApiResponse(description="Accepted")

# 208
RESPONSE_ALREADY_REPORTED = OpenApiResponse(description="Already Reported")

# 400
RESPONSE_BAD_REQUEST = OpenApiResponse(description="Bad Request")

# 401
RESPONSE_UNAUTHORIZED = OpenApiResponse(description="Unauthorized")

# 403
RESPONSE_FORBIDDEN = OpenApiResponse(description="Forbidden")

# 404
RESPONSE_NOT_FOUND = OpenApiResponse(description="Not Found")

# 409
RESPONSE_CONFLICT = OpenApiResponse(description="Conflict")
