import logging
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError

logger = logging.getLogger('hrms.api')

def custom_exception_handler(exc, context):
    """
    Standardizes error responses across all HRMS endpoints.
    Ensures that internal stack traces, database schema details, and 
    file paths are never leaked to clients, while preserving descriptive 
    validation messages for frontend forms.
    """
    # Transform Django core ValidationError into DRF ValidationError
    if isinstance(exc, DjangoValidationError):
        if hasattr(exc, 'message_dict'):
            exc = DRFValidationError(detail=exc.message_dict)
        elif hasattr(exc, 'messages'):
            exc = DRFValidationError(detail=exc.messages)
        else:
            exc = DRFValidationError(detail=str(exc))

    response = exception_handler(exc, context)

    if response is not None:
        custom_data = {
            'status': 'error',
            'code': response.status_code,
        }
        
        if isinstance(response.data, dict):
            if 'detail' in response.data:
                custom_data['detail'] = response.data['detail']
            else:
                custom_data['detail'] = 'Validation failed.'
                custom_data['errors'] = response.data
        elif isinstance(response.data, list):
            custom_data['detail'] = response.data[0] if response.data else 'Error occurred.'
            custom_data['errors'] = response.data
        else:
            custom_data['detail'] = str(response.data)

        response.data = custom_data
        return response

    # Sanitize unhandled 500 exceptions
    view_name = context.get('view').__class__.__name__ if context.get('view') else 'UnknownView'
    logger.exception(f"Unhandled API exception in {view_name}: {str(exc)}")

    return Response({
        'status': 'error',
        'code': 500,
        'detail': 'An unexpected server error occurred. Please contact system administration.'
    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

