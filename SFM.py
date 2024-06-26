import cv2
import numpy as np
from matplotlib import pyplot as plt
import os 
from scipy.optimize import least_squares
from tqdm import tqdm 

class ImageLoader:
    """
    Class for loading and downscaling images, as well as handling camera intrinsics.

    Attributes:
    -----------
    K : np.ndarray
        Camera intrinsic matrix.
    image_list : list
        List of image paths.
    path : str
        Current working directory.
    factor : float
        Downscale factor.
    """
    def __init__(self, img_dir:str, downscale_factor:float):
        """
        Initialize the ImageLoader with directory and downscale factor.

        Parameters:
        -----------
        img_dir : str
            Directory containing images and intrinsic matrix.
        downscale_factor : float
            Factor by which to downscale the images and intrinsic matrix.
        """
        # Load camera intrinsic matrix from file
        with open(img_dir + '\\K.txt') as f:
            self.K = np.array(list((map(lambda x:list(map(lambda x:float(x), x.strip().split(' '))),f.read().split('\n')))))
            self.image_list = []

        # Load image file paths    
        for image in sorted(os.listdir(img_dir)):
            if image[-4:].lower() == '.jpg' or image[-5:].lower() == '.png':
                self.image_list.append(img_dir + '\\' + image)
        
        self.path = os.getcwd()
        self.factor = downscale_factor
        self.downscale_instrinsics()

    def downscale_image(self, image):
        """
        Downscale an image using pyramid down method.

        Parameters:
        -----------
        image : np.ndarray
            Image to be downscaled.

        Returns:
        --------
        np.ndarray
            Downscaled image.
        """
        for _ in range(1,int(self.factor / 2) + 1):
            image = cv2.pyrDown(image)
        return image

    def downscale_instrinsics(self) -> None:
        """
        Downscale the camera intrinsic matrix by the downscale factor.
        """
        self.K[0, 0] /= self.factor
        self.K[1, 1] /= self.factor
        self.K[0, 2] /= self.factor
        self.K[1, 2] /= self.factor

    
class StructurefromMotion:
    """
    Class for performing Structure from Motion (SfM).

    Attributes:
    -----------
    img_obj : ImageLoader
        Instance of ImageLoader class.
    """
    def __init__(self, img_dir=str, downscale_factor:float = 2.0):
        """
        Initialize the StructurefromMotion with image directory and downscale factor.

        Parameters:
        -----------
        img_dir : str
            Directory containing images and intrinsic matrix.
        downscale_factor : float
            Factor by which to downscale the images and intrinsic matrix.
        """
        self.img_obj =ImageLoader(img_dir, downscale_factor)

    def feature_matching(self, image_0, image_1) -> tuple:
        """
        Perform feature matching between two images using SIFT.

        Parameters:
        -----------
        image_0 : np.ndarray
            First image.
        image_1 : np.ndarray
            Second image.

        Returns:
        --------
        tuple
            Matched feature points from both images.
        """
        sift = cv2.SIFT_create()
        # Detect and compute SIFT keypoints and descriptors
        key_points0, descriptors_0 = sift.detectAndCompute(cv2.cvtColor(image_0, cv2.COLOR_BGR2GRAY), None)
        key_points1, descriptors_1 = sift.detectAndCompute(cv2.cvtColor(image_1, cv2.COLOR_BGR2GRAY), None)

        # Match descriptors using BFMatcher with k-nearest neighbors
        bf = cv2.BFMatcher()
        matches = bf.knnMatch(descriptors_0, descriptors_1, k=2)
        feature = []
        for m, n in matches:
            if m.distance < 0.70 * n.distance:
                feature.append(m)
        return np.float32([key_points0[m.queryIdx].pt for m in feature]), np.float32([key_points1[m.trainIdx].pt for m in feature])

    def triangulation(self, pts_2d_1, pts_2d_2, proj_matrix_1, proj_matrix_2) -> tuple:
        """
        Triangulate points from two views.

        Parameters:
        -----------
        pts_2d_1 : np.ndarray
            2D points from the first view.
        pts_2d_2 : np.ndarray
            2D points from the second view.
        proj_matrix_1 : np.ndarray
            Projection matrix of the first view.
        proj_matrix_2 : np.ndarray
            Projection matrix of the second view.

        Returns:
        --------
        tuple
            Projection matrices and 3D points.
        """
        # Triangulate points using projection matrices
        point_cloud = cv2.triangulatePoints(pts_2d_1, pts_2d_2, proj_matrix_1.T, proj_matrix_2.T)
        return proj_matrix_1.T, proj_matrix_2.T, (point_cloud/point_cloud[3])
    
    def solve_PnP(self, obj_point, image_point, K, dist_coeff, rot_vector, initial) -> tuple:
        """
        Solve Perspective-n-Point (PnP) problem.

        Parameters:
        -----------
        obj_point : np.ndarray
            3D object points.
        image_point : np.ndarray
            2D image points.
        K : np.ndarray
            Camera intrinsic matrix.
        dist_coeff : np.ndarray
            Distortion coefficients.
        rot_vector : np.ndarray
            Rotation vector.
        initial : int
            Flag indicating whether it's the initial call.

        Returns:
        --------
        tuple
            Rotation matrix, translation vector, image points, object points, and rotation vector.
        """
        if initial == 1:
            obj_point=obj_point[:,0,:]
            image_point = image_point.T
            rot_vector = rot_vector.T

        # Solve PnP with RANSAC to estimate camera pose    
        _, rot_vector_calc, tran_vector, inlier = cv2.solvePnPRansac(obj_point, image_point, K, dist_coeff, cv2.SOLVEPNP_ITERATIVE)
        rot_matrix, _ =cv2.Rodrigues(rot_vector_calc)

        if inlier is not None:
            image_point=image_point[inlier[:,0]]
            obj_point=obj_point[inlier[:,0]]
            rot_vector = rot_vector[inlier[:,0]]
        return rot_matrix, tran_vector,image_point,obj_point,rot_vector
    
    def find_common_points(self, image_points_1, image_points_2, image_points_3) -> tuple:
        """
        Find common points between three sets of image points.

        Parameters:
        -----------
        image_points_1 : np.ndarray
            Image points from the first image.
        image_points_2 : np.ndarray
            Image points from the second image.
        image_points_3 : np.ndarray
            Image points from the third image.

        Returns:
        --------
        tuple
            Indices of common points and mask arrays.
        """
        cm_points_1= []
        cm_points_2= []
        # Find common points between first and second set of image points
        for i in range(image_points_1.shape[0]):
            a= np.where(image_points_2 == image_points_1[i, :])
            if a[0].size !=0:
                cm_points_1.append(i)
                cm_points_2.append(a[0][0])

        # Mask arrays to remove common points
        mask_array_1 = np.ma.array(image_points_2, mask= False)
        mask_array_1.mask[cm_points_2] = True
        mask_array_1 = mask_array_1.compressed()
        mask_array_1=mask_array_1.reshape(int(mask_array_1.shape[0]/2),2)

        mask_array_2 = np.ma.array(image_points_3, mask=False)
        mask_array_2.mask[cm_points_2] = True
        mask_array_2 = mask_array_2.compressed()
        mask_array_2 = mask_array_2.reshape(int(mask_array_2.shape[0] / 2), 2)
        print(" Shape of New Array", mask_array_1.shape, mask_array_2.shape)
        return np.array(cm_points_1), np.array(cm_points_2), mask_array_1, mask_array_2

    def reproj_error(self, obj_points, image_points, transform_matrix, K, homogenity) -> tuple:
        """
        Compute reprojection error.

        Parameters:
        -----------
        obj_points : np.ndarray
            3D object points.
        image_points : np.ndarray
            2D image points.
        transform_matrix : np.ndarray
            Transformation matrix.
        K : np.ndarray
            Camera intrinsic matrix.
        homogenity : int
            Flag indicating whether the points are homogeneous.

        Returns:
        --------
        tuple
            Reprojection error and object points.
        """
        rot_matrix = transform_matrix[:3,:3]
        tran_vector = transform_matrix[:3, 3]
        rot_vector, _ = cv2.Rodrigues(rot_matrix)

        if homogenity == 1:
            obj_points= cv2.convertPointsFromHomogeneous(obj_points.T)
        # Project 3D points back to 2D    
        image_points_calc, _ = cv2.projectPoints(obj_points, rot_vector, tran_vector, K, None)
        image_points_calc = np.float32(image_points_calc[:,0,:])
        # Calculate reprojection error
        total_error = cv2.norm(image_points_calc, np.float32(image_points.T) if homogenity == 1 else np.float32(image_points), cv2.NORM_L2)
        return total_error/ len(image_points_calc), obj_points
            
    def optimize_reproj_error(self, obj_points) -> np.array:
        """
        Optimize reprojection error.

        Parameters:
        -----------
        obj_points : np.ndarray
            Object points.

        Returns:
        --------
        np.array
            Optimized reprojection error.
        """
        transform_matrix = obj_points[0:12].reshape((3,4))
        K = obj_points[12:21].reshape((3,3))
        rest= int(len(obj_points[21:])* 0.4)
        p = obj_points[21:21 + rest].reshape((2, int(rest/2))).T
        obj_points = obj_points[21 + rest:].reshape((int(len(obj_points[21 + rest:])/3),3))
        rot_matrix = transform_matrix[:3,:3]
        tran_vector = transform_matrix[:3, 3]
        rot_vector , _ = cv2.Rodrigues(rot_matrix)
        image_points ,_ =cv2.projectPoints(obj_points, rot_vector, tran_vector, K, None)
        image_points = image_points[:,0,:]
        error = [(p[idx]- image_points[idx])**2 for idx in range(len(p))]
        return np.array(error).ravel()/len(p)
    
    def compute_bundle_adjustment(self, _3d_point, opt, transform_matrix_new, K, r_error) -> tuple:
        """
        Compute bundle adjustment.

        Parameters:
        -----------
        _3d_point : np.ndarray
            3D points.
        opt : np.ndarray
            Optimized points.
        transform_matrix_new : np.ndarray
            New transformation matrix.
        K : np.ndarray
            Camera intrinsic matrix.
        r_error : float
            Reprojection error.

        Returns:
        --------
        tuple
            Adjusted 3D points, optimized points, and transformation matrix.
        """
        # Concatenate all optimization variables
        opt_variables = np.hstack((transform_matrix_new.ravel(), K.ravel()))
        opt_variables= np.hstack((opt_variables, opt.ravel()))
        opt_variables= np.hstack((opt_variables, _3d_point.ravel()))

        # Perform least squares optimization
        values_corrected = least_squares(self.optimize_reproj_error, opt_variables, g_tolrance= r_error).x
        K = values_corrected[12:21].reshape((3,3))
        rest = int(len(values_corrected[21:])* 0.4)
        return values_corrected[21+rest:].reshape((int(len(values_corrected[21+rest:])/3),3)), values_corrected[21:21 + rest].reshape((2, int(rest/2))).T, values_corrected[0:12].reshape((3,4))

    def save_to_ply(self, path, point_cloud, colors, bundle_adjustment_enabled):
        """
        Save point cloud to a PLY file.

        Parameters:
        -----------
        path : str
            Path to save the PLY file.
        point_cloud : np.ndarray
            3D point cloud.
        colors : np.ndarray
            Colors associated with the point cloud.
        bundle_adjustment_enabled : bool
            Flag indicating whether bundle adjustment is enabled.
        """
        if bundle_adjustment_enabled:
            output_dir = os.path.join(self.img_obj.path, 'Results with Bundle Adjustment')
        else:
            output_dir = os.path.join(self.img_obj.path, 'Results')

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        ply_filename = os.path.join(output_dir, self.img_obj.image_list[0].split(os.sep)[-1].split('.')[0] + '.ply')
        out_points = point_cloud.reshape(-1,3) * 200
        out_colors = colors.reshape(-1, 3)
        print(out_colors.shape, out_points.shape)
        verts = np.hstack([out_points, out_colors])

        mean = np.mean(verts[:,:3], axis= 0)
        scaled_verts = verts[:,:3]- mean
        dist= np.sqrt(scaled_verts[:,0]** 2 + scaled_verts[:,1] ** 2 + scaled_verts[:,2] **2)
        indx= np.where(dist < np.mean(dist) + 300)
        verts = verts[indx]
        ply_header = '''ply
            format ascii 1.0
            element vertex {}
            property float x
            property float y
            property float z
            property uchar blue
            property uchar green
            property uchar red
            end_header
            '''.format(len(verts))
        with open(ply_filename, 'w') as f:
            f.write(ply_header)
            np.savetxt(f, verts, '%f %f %f %d %d %d')

    def __call__(self, bundle_adjustmenet_enabled: bool = False):
        """
        Run the Structure from Motion pipeline.

        Parameters:
        -----------
        bundle_adjustment_enabled : bool
            Flag indicating whether bundle adjustment is enabled.
        """
        cv2.namedWindow('image', cv2.WINDOW_NORMAL)
        pose_array = self.img_obj.K.ravel()
        transform_matrix_0 = np.array([[1,0,0,0],[0,1,0,0],[0,0,1,0]])
        transform_matrix_1 = np.empty((3,4))

        # Initial pose (camera extrinsic matrix)
        pose_0= np.matmul(self.img_obj.K, transform_matrix_0)
        pose_1 = np.empty((3,4))
        total_points= np.zeros((1,3))
        total_colors = np.zeros((1,3))

        # Load and downscale the first two images
        image_0 = self.img_obj.downscale_image(cv2.imread(self.img_obj.image_list[0]))
        image_1 = self.img_obj.downscale_image(cv2.imread(self.img_obj.image_list[1]))

        # Feature matching between the first two images
        features_0, features_1 = self.feature_matching(image_0, image_1)

        # Compute essential matrix and recover pose
        essential_matrix, em_mask = cv2.findEssentialMat(features_0, features_1, self.img_obj.K, method=cv2.RANSAC, prob=0.999, threshold=0.4, mask=None)
        features_0 = features_0[em_mask.ravel()==1]
        features_1 = features_1[em_mask.ravel()==1]

        _, rot_matrix, tran_matrix , em_mask = cv2.recoverPose(essential_matrix, features_0, features_1, self.img_obj.K)
        features_0 = features_0[em_mask.ravel()>0]
        features_1 = features_1[em_mask.ravel() > 0] 
        transform_matrix_1[:3, :3]= np.matmul(rot_matrix, transform_matrix_0[:3,:3])
        transform_matrix_1[:3,3]= transform_matrix_0[:3, 3] + np.matmul(transform_matrix_0[:3,:3], tran_matrix.ravel())

        pose_1 = np.matmul(self.img_obj.K, transform_matrix_1)

        # Triangulate points between the first two images
        features_0, features_1, points_3d = self.triangulation(pose_0, pose_1, features_0, features_1)
        error, points_3d= self.reproj_error(points_3d, features_1, transform_matrix_1, self.img_obj.K, homogenity=1)
        print("Reprojection error for first two images:", error)
        _,_, features_1, points_3d, _ = self.solve_PnP(points_3d, features_1, self.img_obj.K, np.zeros((5,1), dtype=np.float32), features_0, initial=1)

        total_images = len(self.img_obj.image_list) - 2
        pose_array = np.hstack((np.hstack((pose_array, pose_0.ravel())), pose_1.ravel()))

        # after the first two images, start adding a single image to the group and repeat till last image is added.
        threshold = 0.5
        for i in tqdm(range(total_images)):
            image_2 = self.img_obj.downscale_image(cv2.imread(self.img_obj.image_list[i+2]))
            features_cur, features_2 = self.feature_matching(image_1, image_2)

            if i !=0:
                features_0 , features_1, points_3d = self. triangulation(pose_0, pose_1, features_0, features_1)
                features_1= features_1.T
                points_3d= cv2.convertPointsFromHomogeneous(points_3d.T)

            cm_points_0, cm_points_1, cm_mask_0, cm_mask_1= self.find_common_points(features_1,features_cur, features_2)
            cm_points_2 = features_2[cm_points_1]
            cm_points_cur = features_cur[cm_points_1]

            rot_matrix, tran_matrix, cm_points_2, points_3d, cm_points_cur = self.solve_PnP(points_3d[cm_points_0], cm_points_2, self.img_obj.K, np.zeros((5, 1), dtype=np.float32), cm_points_cur, initial = 0)
            transform_matrix_1= np.hstack((rot_matrix, tran_matrix))
            pose_2 = np.matmul(self.img_obj.K, transform_matrix_1)

            error, points_3d= self.reproj_error(points_3d, cm_points_2, transform_matrix_1, self.img_obj.K, homogenity=0)

            cm_mask_0, cm_mask_1, points_3d= self.triangulation(pose_1, pose_2, cm_mask_0, cm_mask_1)
            error, points_3d = self.reproj_error(points_3d, cm_mask_1, transform_matrix_1, self.img_obj.K, homogenity=1)
            print("Reprojection error:", error)
            pose_array = np.hstack((pose_array, pose_2.ravel()))

            if bundle_adjustmenet_enabled:
                points_3d, cm_mask_1, transform_matrix_1 = self.compute_bundle_adjustment(points_3d, cm_mask_1, transform_matrix_1, self.img_obj.K, threshold)
                pose_2 = np.matmul(self.img_obj.K, transform_matrix_1)
                error, points_3d = self.reproj_error(points_3d, cm_mask_1, transform_matrix_1, self.img_obj.K, homogenity = 0)
                print("Reprojection error after Bundle Adjustment: ",error)
                total_points = np.vstack((total_points, points_3d))
                points_left = np.array(cm_mask_1, dtype=np.int32)
                color_vector = np.array([image_2[l[1], l[0]] for l in points_left])
                total_colors = np.vstack((total_colors, color_vector))
            else:
                total_points = np.vstack((total_points, points_3d[:, 0, :]))
                points_left = np.array(cm_mask_1, dtype=np.int32)
                color_vector = np.array([image_2[l[1], l[0]] for l in points_left.T])
                total_colors = np.vstack((total_colors, color_vector)) 
   
            transform_matrix_0 = np.copy(transform_matrix_1)
            pose_0 = np.copy(pose_1)
            plt.scatter(i, error)
            plt.pause(0.05)

            image_0 = np.copy(image_1)
            image_1 = np.copy(image_2)
            features_0 = np.copy(features_cur)
            features_1 = np.copy(features_2)
            pose_1 = np.copy(pose_2)
            cv2.imshow(self.img_obj.image_list[0].split('\\')[-2], image_2)
            if cv2.waitKey(1) & 0xff == ord('q'):
                break
        cv2.destroyAllWindows()

        if bundle_adjustmenet_enabled:
            plot_dir = os.path.join(self.img_obj.path, 'Results with Bundle Adjustment')
        else:
            plot_dir = os.path.join(self.img_obj.path, 'Results')

        if not os.path.exists(plot_dir):
            os.makedirs(plot_dir)

        plt.xlabel('Image Index')
        plt.ylabel('Reprojection Error')
        plt.title('Reprojection Error Plot')
        plt.savefig(os.path.join(plot_dir, 'reprojection_errors.png'))
        plt.close()

        print("Saving to .ply file.......")
        print(total_points.shape, total_colors.shape)
        self.save_to_ply(self.img_obj.path, total_points, total_colors, bundle_adjustmenet_enabled)
        print("Saved the point cloud to .ply file!!!")
        np.savetxt(self.img_obj.path + '\\Results\\' + self.img_obj.image_list[0].split('\\')[-2]+'_pose_array.csv', pose_array, delimiter = '\n')

if __name__ == '__main__':
    sfm = StructurefromMotion("Datasets\\fountain-P11")
    sfm()
    # sfm(bundle_adjustment_enabled=True)
