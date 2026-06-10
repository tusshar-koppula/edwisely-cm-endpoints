@timetable.route('/getSectionStudents', methods = ['GET'])
@authorize
def getSectionStudents(user):#
    user_id = user.get('user_id')
    csm_id = int(request.args.get('csm_id'))
    section_id = int(request.args.get('section_id'))
    date = request.args.get('date')
    faculty_class_hour_id = request.args.get('faculty_class_hour_id')
    replicate_attendance = request.args.get('replicate_attendance')
    replicate_first_attendance = request.args.get('replicate_first_attendance')
    replicate_previous_attendance = request.args.get('replicate_previous_attendance')

    if not csm_id: return jsonify({"status":422,"message": "csm_id is missing"})
    if not section_id: return jsonify({"status":422,"message": "section_id is missing"})
    if not date : return jsonify({"status":422,"message": "date is missing"})
    if not faculty_class_hour_id : return jsonify({"status":422,"message": "faculty_class_hour_id is missing"})

    #print(replicate_attendance)

    try:
        data = timetable_data.getSectionStudents1V2(user_id,csm_id,section_id,date,faculty_class_hour_id, replicate_attendance, replicate_first_attendance, replicate_previous_attendance)
        if data :
            return jsonify({"status":200, "message" : "Successfully fetched Data", "data" : data})
        else :
            return jsonify({"status":400, "message":"No Data Found!!"})

    except Exception as e:
        # #print(e)
        subject = "server:- {}, Error in /timetable/getSectionStudents".format(os.environ.get('FLASK_ENV'))
        content = sendgrid.Content("text/plain", "{}".format(e))
        sendgrid.sendmail(subject,content)
        app.logger.error('/timetable/getSectionStudents - EXCEPTION: {}'.format(e))
        return jsonify({"status":500,"message": 'Failure'})