import cloudinary
import cloudinary.uploader
import os
from dotenv import load_dotenv
from fastapi import HTTPException

load_dotenv()

CLOUDINARY_UPLOAD_PRESET = os.getenv("CLOUDINARY_UPLOAD_PRESET")


def upload_image_to_cloudinary(file_bytes, filename):
    """
    Upload an image file to Cloudinary using unsigned upload (preset-based).
    
    Args:
        file_bytes: Raw bytes of the file
        filename: Name of the file being uploaded
        
    Returns:
        dict: Cloudinary response with URL and public_id
    """
    try:
        result = cloudinary.uploader.upload(
            file_bytes,
            upload_preset=CLOUDINARY_UPLOAD_PRESET,
            public_id=filename.split('.')[0],
            resource_type="auto"
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to upload image to Cloudinary: {str(e)}"
        )


def delete_image_from_cloudinary(public_id):
    """
    Delete an image from Cloudinary.
    
    Args:
        public_id: The public ID of the image to delete
        
    Returns:
        dict: Cloudinary response
    """
    try:
        result = cloudinary.uploader.destroy(public_id)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to delete image from Cloudinary: {str(e)}"
        )


def get_cloudinary_url(public_id, width=None, height=None):
    """
    Generate a Cloudinary URL for an image with optional transformations.
    
    Args:
        public_id: The public ID of the image
        width: Optional width for resizing
        height: Optional height for resizing
        
    Returns:
        str: Cloudinary URL
    """
    try:
        url = cloudinary.CloudinaryImage(public_id).build_url(
            width=width,
            height=height,
            crop="fill" if width or height else None
        )
        return url
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to generate Cloudinary URL: {str(e)}"
        )
