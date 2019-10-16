# AWS Auto Thumbnail
# Generates thumbnails automatically for files placed in folder

import boto3
import botocore
import datetime
import logging
import sys
import os
from ctypes import cdll
from os.path import join

# manually load libraries and set paths so native libraries can be used
exec_dir = os.getcwd()
lib_dir = join(exec_dir, 'lib')
sys.path.append(lib_dir)
from wand.image import Image

os.environ['MAGICK_HOME'] = exec_dir # required for Wand 

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    # connect to s3
    s3 = boto3.resource('s3', region_name='us-east-2')

    if event['Records'] is None:
        exit()
        
    for record in event['Records']:
        bucket_name = record['s3']['bucket']['name']
        key_path = record['s3']['object']['key']

        # get filename withoput path
        filename = os.path.basename(record['s3']['object']['key'])

        # set bucket
        bucket = s3.Bucket(bucket_name)
        
        # grab object and its ACLs
        object = bucket.Object(key_path)
        acl = s3.meta.client.get_object_acl(Bucket=bucket_name,Key=key_path)
        
        # acl
        public_check = {
            'Grantee': {
                'Type': 'Group', 
                'URI': 'http://acs.amazonaws.com/groups/global/AllUsers'
            }, 
            'Permission': 'READ'
        }
        
        if public_check in acl['Grants']:
            acl_primary = 'public-read'
        else:
            acl_primary = 'private'
        
        # get object ACL
        grants = {'Grants' : acl['Grants']}
        logger.info('event {} on bucket {}/{} with ACL {}'.format(event, bucket_name, key_path, acl_primary))
    
        # get file 
        temp_filename = '/tmp/image.jpg'
        thumb_filename =  '/tmp/thumbnail.jpg'
        
        bucket.download_file(key_path,temp_filename)
        
        # generate thumbnail
        thumbnails = {
            'moodle': {'width':100,'height':100},
            'directory': {'width':120,'height':170},
            'icon' : {'width':28,'height':28}
        }

        # if thumbails were recently made skip making them -- user can only upload a new thumbnail every 10 seconds
        # important due to multi event processing and not wanting to have db for request id check
        try:
            object_summary = s3.ObjectSummary(bucket_name, next(iter(thumbnails))+'/'+filename)
            if object_summary is not None and isinstance(object_summary.last_modified, datetime.date):
                wait_timelimit = 10
                datetime_summary = object_summary.last_modified.strftime('%Y-%m-%d %H:%M:%S')
                datetime_last_modified = datetime.datetime.strptime(datetime_summary,'%Y-%m-%d %H:%M:%S')
                datetime_check = datetime_last_modified + datetime.timedelta(seconds=wait_timelimit)
                datetime_now = datetime.datetime.utcnow()
                if datetime_now < datetime_check:
                    logger.info('skip thumbnails due last modified date {} (need to wait {} seconds past {})'.format(datetime_last_modified, wait_timelimit, datetime_now))
                    continue
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == "404":
                logger.info('thumbnail not found')
            else:
                pass
        
        for folder, new_size in thumbnails.items():
            object_key = folder+'/'+filename

            try:
                # create thumbnail that are just the right size while maintaining aspect ratio
                with Image(width=new_size['width'], height=new_size['height']) as outerImg:                                                                                                                           
                    with Image(filename=temp_filename) as img:
                        # scale to size
                        if img.width >= img.height:
                            # scale by hieght
                            scale_by = 'height'
                            desired_height = int(img.height * (new_size['width']/img.width))
                            desired_width = new_size['width']
                        else:
                            # scale by width
                            scale_by = 'width'
                            desired_height = new_size['height']
                            desired_width = int(img.width * (new_size['height']/img.height))
                            
                        # scale up to cover
                        if desired_height < new_size['height']:
                            difference = new_size['height'] - desired_height
                            desired_height += difference
                            desired_width += difference
                            
                        if desired_width < new_size['width']:
                            difference = new_size['width'] - desired_width
                            desired_height += difference
                            desired_width += difference
    
                        logger.info('scaling by {} to {} x {}'.format(scale_by,desired_height, desired_width))
        
                        top = int((new_size['height'] - desired_height) / 2)
                        left = int((new_size['width'] - desired_width) / 2)
                        
                        img.resize(desired_width,desired_height)
    
                        outerImg.format = img.format.lower()
    
                        outerImg.composite(img, left, top)                                                                                                                                                                                            
                        outerImg.save(filename=thumb_filename)
    
                
                # upload thumbail file and set ACL
                s3.meta.client.upload_file(thumb_filename, bucket_name, object_key)
                s3.meta.client.put_object_acl(ACL=acl_primary,Bucket=bucket_name,Key=object_key)
                logger.info('uploading thumbnail {} and setting ACL {}'.format(object_key, acl_primary))
            except ValueError:
                logger.info('failed to create thumbnail')
            