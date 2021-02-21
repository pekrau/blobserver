"Blob serve, metadata display, upload and update."

import hashlib
import http.client
import os
import os.path

import flask

from blobserver import constants
from blobserver import utils
from blobserver.saver import BaseSaver

def init(app):
    "Initialize the database; create blob table."
    db = utils.get_db(app)
    with db:
        db.execute("CREATE TABLE IF NOT EXISTS blobs"
                   "(iuid TEXT PRIMARY KEY,"
                   " filename TEXT NOT NULL,"
                   " username TEXT NOT NULL,"
                   " description TEXT,"
                   " md5 TEXT NOT NULL,"
                   " sha256 TEXT NOT NULL,"
                   " sha512 TEXT NOT NULL,"
                   " size INTEGER NOT NULL,"
                   " created TEXT NOT NULL,"
                   " modified TEXT NOT NULL)")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS"
                   " blobs_filename_index ON blobs (filename COLLATE NOCASE)")


blueprint = flask.Blueprint("blob", __name__)

@blueprint.route("/", methods=["GET", "POST"])
@utils.login_required
def upload():
    "Upload a new blob."
    if utils.http_GET():
        return flask.render_template("blob/upload.html")

    elif utils.http_POST():
        infile = flask.request.files.get("file")
        if not infile:
            return utils.error("No file provided.")
        if get_blob_data(infile.filename):
            return utils.error("Blob already exists; do update instead.")
        try:
            with BlobSaver() as saver:
                saver["description"] = flask.request.form.get("description")
                saver["filename"] = infile.filename
                saver["content"] = infile.read()
                saver["username"] = flask.g.current_user["username"]
        except ValueError as error:
            return utils.error(error)
        return flask.redirect(
            flask.url_for("blob.info", filename=saver["filename"]))

@blueprint.route("/<filename>", methods=["GET", "POST", "PUT", "DELETE"])
def blob(filename):
    if utils.http_GET():
        data = get_blob_data(filename)
        if not data:
            # Just send error code; appropriate for when used as a service.
            flask.abort(http.client.NOT_FOUND)
        return flask.send_from_directory(
            flask.current_app.config["STORAGE_DIRPATH"], filename)

    elif utils.http_PUT():
        # Create a new blob.
        raise NotImplementedError

    elif utils.http_DELETE():
        data = get_blob_data(filename)
        if not data:
            # Just send error code; appropriate for when used as a service.
            flask.abort(http.client.NOT_FOUND)
        if not allow_delete(data):
            # Just send error code; appropriate for when used as a service.
            flask.abort(http.client.FOBRIDDEN)
        delete_blob(data)
        utils.flash_message(f"Deleted blob {data['filename']}")
        return flask.redirect(
            flask.url_for("blobs.user", username=data["username"]))

@blueprint.route("/<filename>/info")
def info(filename):
    data = get_blob_data(filename)
    if not data:
        return utils.error("No such blob.")
    return flask.render_template("blob/info.html", 
                                 data=data,
                                 allow_update=allow_update(data),
                                 allow_delete=allow_delete(data))

@blueprint.route("/<filename>/update", methods=["GET", "POST"])
@utils.login_required
def update(filename):
    data = get_blob_data(filename)
    if not data:
        return utils.error("No such blob.")
    if not allow_update(data):
        return utils.error("You may not update the blob.")

    if utils.http_GET():
        return flask.render_template("blob/update.html", data=data)

    elif utils.http_POST():
        try:
            with BlobSaver(data) as saver:
                saver["description"] = flask.request.form.get("description")
                infile = flask.request.files.get("file")
                if infile:
                    saver["filename"] = infile.filename
                    saver["content"] = infile.read()
        except ValueError as error:
            return utils.error(error)
        return flask.redirect(
            flask.url_for("blob.info", filename=data["filename"]))

@blueprint.route("/<filename>/logs")
@utils.login_required
def logs(filename):
    "Display the log records of the given blob."
    data = get_blob_data(filename)
    if not data:
        return utils.error("No such blob.")
    return flask.render_template(
        "logs.html",
        title=f"Blob {data['filename']}",
        cancel_url=flask.url_for(".info", filename=data["filename"]),
        logs=utils.get_logs(data["iuid"]))


class BlobSaver(BaseSaver):
    "Save the blob."

    LOG_EXCLUDE_PATHS = [["content"], ["modified"]]  # Exclude from log info.

    def finalize(self):
        for key in ["filename", "content", "username"]:
            if not self.doc.get(key):
                raise ValueError(f"Invalid blob: {key} not set.")
        if self.doc["filename"].startswith("_"):
            raise ValueError("Filename is not allowed to start with"
                             " an underscore character.")
        if flask.g.current_user["quota"]:
            if len(self.doc["content"]) + flask.g.current_user["blobs_size"] > \
               flask.g.current_user["quota"]:
                raise ValueError("User's quota cannot accommodate the blob.")

    def upsert(self):
        if "content" in self.doc:  # The content has changed; insert or update.
            filepath = os.path.join(flask.current_app.config['STORAGE_DIRPATH'],
                                    self.doc["filename"])
            with open(filepath, "wb") as outfile:
                outfile.write(self.doc["content"])
            md5 = hashlib.new("md5")
            md5.update(self.doc["content"])
            sha256 = hashlib.new("sha256")
            sha256.update(self.doc["content"])
            sha512 = hashlib.new("sha512")
            sha512.update(self.doc["content"])
            cursor = flask.g.db.cursor()
            rows = list(cursor.execute("SELECT COUNT(*) FROM blobs WHERE"
                                       " filename=?",
                                       (self.doc["filename"],)))
            if rows[0][0] == 0:
                cursor.execute("INSERT INTO blobs ('iuid', 'filename',"
                               " 'username', 'description', 'md5', 'sha256',"
                               " 'sha512', 'size', 'modified', 'created')"
                               " VALUES (?,?,?,?,?,?,?,?,?,?)",
                               (self.doc["iuid"],
                                self.doc["filename"],
                                flask.g.current_user["username"],
                                self.doc.get("description"),
                                md5.hexdigest(),
                                sha256.hexdigest(),
                                sha512.hexdigest(),
                                len(self.doc["content"]),
                                self.doc["modified"],
                                self.doc["created"]))
            else:
                cursor.execute("UPDATE blobs SET (description=?, md5=?,"
                               " sha256=?,sha512=?, size=?, modified=?)"
                               " WHERE filename=?",
                               (self.doc.get("description"),
                                md5.hexdigest(),
                                sha256.hexdigest(),
                                sha512.hexdigest(),
                                len(self.doc["content"]),
                                self.doc["filename"],
                                self.doc["modified"]))
        else:  # Only the description has changed; only update is relevant.
            cursor.execute("UPDATE blobs SET (description=?) WHERE filename=?",
                           (self.doc.get("description")))

def get_blob_data(filename):
    """Return the data (not the content) for the blob.
    Return None if not found.
    """
    if filename.startswith("_"): return None
    cursor = flask.g.db.cursor()
    rows = list(cursor.execute("SELECT * FROM blobs WHERE filename=?",
                               (filename,)))
    if rows:
        return dict(zip(rows[0].keys(), rows[0]))
    else:
        return None

def get_most_recent_blobs():
    "Return the most recently modified blobs."
    cursor = flask.g.db.cursor()
    rows = list(cursor.execute("SELECT * FROM blobs"
                               " ORDER BY modified DESC LIMIT ?",
                               (flask.current_app.config["MOST_RECENT"],)))
    return [dict(zip(r.keys(), r)) for r in rows]

def delete_blob(data):
    "Delete the blob and its logs."
    with flask.g.db:
        flask.g.db.execute("DELETE FROM logs WHERE docid=?", (data["iuid"],))
        flask.g.db.execute("DELETE FROM blobs WHERE filename=?",
                           (data["filename"],))
        filepath = os.path.join(flask.current_app.config['STORAGE_DIRPATH'],
                                data["filename"])
        os.remove(filepath)

def allow_update(data):
    if flask.g.am_admin: return True
    if flask.current_user["username"] == data["username"]: return True
    return False

def allow_delete(data):
    if flask.g.am_admin: return True
    if flask.current_user["username"] == data["username"]: return True
    return False
