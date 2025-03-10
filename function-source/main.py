def process_pipeline(event, context):
    """Cloud Function entry point that processes a Pub/Sub event."""
    print("Hello World! This is the immunization pipeline function.")
    
    # Print environment variables for debugging
    import os
    print(f"BULK_QUERY_BUCKET: {os.environ.get('BULK_QUERY_BUCKET')}")
    print(f"AISR_DOWNLOADS_BUCKET: {os.environ.get('AISR_DOWNLOADS_BUCKET')}")
    print(f"TRANSFORMED_BUCKET: {os.environ.get('TRANSFORMED_BUCKET')}")
    
    # In the future, you would call your actual pipeline here
    # from data_pipeline import run_pipeline
    # run_pipeline(...)
    
    return 'Hello World pipeline completed successfully'