def get_file_extension(filename: str, content_type: str) -> str:
    """
    Détermine l'extension du fichier.
    
    Args:
        filename: Nom du fichier original
        content_type: Type MIME
        
    Returns:
        Extension avec le point (ex: '.jpg')
    """
    # Essayer d'abord depuis le nom de fichier
    if filename and '.' in filename:
        return '.' + filename.split('.')[-1].lower()
    
    # Fallback sur le content-type
    content_type_map = {
        'image/jpeg': '.jpg',
        'image/jpg': '.jpg',
        'image/png': '.png',
        'image/webp': '.webp'
    }
    
    return content_type_map.get(content_type, '.jpg')